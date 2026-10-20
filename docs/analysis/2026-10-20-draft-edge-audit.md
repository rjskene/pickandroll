# Draft edge audit: the nine cash-league drafts of 2026-10-17 to 2026-10-19

**Question.** In every cash-league draft the expected categories won climbed steadily from the
benchmark at our first pick to the final roster. Is that rise a real edge over the room, an artifact
of how the benchmark and the objective are built, or selection on noise (the optimizer's curse: the
solver picks the players whose BBM projection is most above everyone else's, and those are the
projections most likely to be wrong)?

**Data.** The eight nine-category drafts with a fidelity archive (252098, 31153 and 224319 on
2026-10-18; 258332, 223259, 230585, 225248 and 258901 on 2026-10-19): 12 teams, 13 rounds, our seat
between 5 and 11, each archive's own board, z (pool 156), ADP, pick log, team totals and score
history. The points league 238174 (2026-10-17) and the keeper league 31822 (2026-10-14) serve as
contrasts. League 251146 (2026-10-17) has only the extension's day log: the dashboard was never
attached (Yahoo had signed the session out and the room autopicked), so it has no solves, no board
and no totals, and is left out. 224319 attached in round 5, so it has no benchmark and nine solves
instead of thirteen. Three outside systems: Yahoo's own season projections and 2025-26 actuals
(already in each archive's player file), and ESPN's 2026-27 projections and 2025-26 actuals (700
players) and FantasyPros' consensus projections (264 players, dated 2026-10-16), both downloaded
on 2026-10-20 and kept under `data/external/<source>/` with a provenance README. Hashtag
Basketball shows thirty players without a subscription and was not usable. Scripts, per-league
tables and the re-solve outputs are in the scratch repository
(`research/draft-edge-2026-10-20/`), outside this one.

**Method.**

- *Trajectory.* The score history's horizon solves, one per board, give expected wins at each of
  our picks; the rise is split into the jumps at our own picks (the solve after the pick minus the
  solve before) and the drift while the eleven others pick.
- *Decomposition.* The session curve is fixed at the attach, so the opponent model cannot move the
  objective within a draft; its effect is measured by re-scoring the final roster on the curve of
  the simulated league and on a curve fitted to the room's twelve drafted rosters, and by the
  empirical analogue of the objective: categories beaten, the mean over the eleven opponents of the
  categories our projected final beats (the room averages 4.5 of 9 by construction). The
  benchmark's availability discount is measured by re-solving every one of our boards offline from
  the archived ledger, with the league survival table and a copy of the session curve, and
  re-scoring each plan with every target obtained (availability 1 for all), which is the plan's
  undiscounted value.
- *Calibration.* For every undrafted player on each of our boards, the availability the model gave
  him for our next pick against whether he was still there; and for every player in a re-solved
  plan, his modelled odds of lasting to his planned pick against whether he did.
- *Cross-system.* Each system's season totals are turned into z on the same 156-player pool with
  the repository's z-score code (percentages by impact), the twelve final rosters are summed, and
  our seat is scored against the room by categories beaten, rank of twelve and matchups won of
  eleven. Players a system does not cover take its replacement z, the mean of the players just
  outside its top 156. A consensus of three is the mean z of Yahoo, ESPN and FantasyPros.
- *Optimizer's curse.* The market and rank gaps of our 104 picks against the room's 1144; our
  roster re-scored with BBM z shrunk 25, 50, 75 and 100 percent toward each other system and toward
  a market prior (the mean z of the players in an ADP neighbourhood of the pick); and a market
  drafter's counterfactual roster in our seat, the best remaining Yahoo rank at each of our picks
  with the room's picks unchanged, scored under every system.

## Verdict

- **The rise within a draft is an artifact of the benchmark, not an edge gained during the
  draft.** The pick-1 plan with every target obtained is already worth what the final roster ends up
  worth; the benchmark discounts it by the odds of losing each target and credits nothing for
  re-planning, and that discount vanishes pick by pick. The drift while others pick is a one-sided
  random walk: 1002 single-pick steps, mean +0.004, 330 above +0.01 and 214 below -0.01.
- **The final rosters are a real edge under BBM and a mid-table roster under everyone else.** Under
  BBM our seat beats 6.3 of 9 categories against the average opponent and ranks first in seven of
  eight rooms. Under Yahoo, ESPN, FantasyPros or their consensus it beats 4.75 to 4.97 and ranks
  3.8 to 5.3 of 12; under last season's actual stats 5.5 and rank 4.
- **Most of the measured edge is BBM disagreeing with the market, which is the optimizer's curse
  signature.** Our picks sit 22 places below their ADP by BBM's rank where the room's sit 18 above;
  BBM rates our picks 1.0 z above the consensus and the room's 0.2 below; nine players fill 43 of
  our 104 picks. A market drafter in our seat would have beaten 4.45 categories under BBM and
  4.7 under the consensus; our rosters beat it by 1.85 under BBM, by 0.06 to 0.42 under the three
  projection systems, and by 0.8 under last season's actuals.
- **A moderate edge survives shrinkage.** With BBM shrunk 25 percent toward the consensus we still
  rank first in seven of eight rooms (6.0 categories); at 50 percent, first in five (5.6); at 75
  percent, first in two (5.2). Whether the remaining edge is real is a question for the season, and
  section 5 says what to record to answer it.

## 1. Trajectory and decomposition

**The trajectory.** Expected wins at each of our thirteen picks (T1) and the split of the rise
(T2). The jumps at our own picks sum to between -0.03 and +0.16 per draft; the drift while the
others pick sums to +0.36 to +0.69, almost all of it positive. The last solve equals the final in
seven drafts; 223259's final is 0.10 below its last solve because the last pick landed (Jakob Poeltl) was not
the last solve's first choice (Ja'Kobe Walter).

*T1. Expected categories won at each of my picks (the on-the-clock solve), by round*

| round | 252098 | 31153 | 224319 | 258332 | 223259 | 230585 | 225248 | 258901 |
|---|---|---|---|---|---|---|---|---|
| 1 | 4.87 | 5.32 |  | 5.38 | 5.45 | 5.47 | 5.53 | 5.51 |
| 2 | 5.11 | 5.42 |  | 5.43 | 5.55 | 5.57 | 5.63 | 5.56 |
| 3 | 5.12 | 5.56 |  | 5.44 | 5.60 | 5.64 | 5.72 | 5.64 |
| 4 | 5.12 | 5.52 |  | 5.45 | 5.66 | 5.71 | 5.77 | 5.67 |
| 5 | 5.09 | 5.67 | 5.00 | 5.52 | 5.72 | 5.84 | 5.85 | 5.83 |
| 6 | 5.10 | 5.68 | 5.08 | 5.57 | 5.84 | 5.89 | 5.94 | 5.87 |
| 7 | 5.15 | 5.74 | 5.11 | 5.65 | 5.94 | 5.92 | 5.97 | 5.94 |
| 8 | 5.15 | 5.78 | 5.16 | 5.76 | 6.02 | 5.97 | 6.12 | 5.95 |
| 9 | 5.18 | 5.83 | 5.26 | 5.79 | 6.05 | 6.05 | 6.14 | 5.96 |
| 10 | 5.15 | 5.87 | 5.33 | 5.87 | 6.09 | 6.00 | 6.11 | 6.00 |
| 11 | 5.20 | 6.01 | 5.43 | 5.98 | 6.18 | 6.07 | 6.18 | 6.12 |
| 12 | 5.21 | 6.09 | 5.51 | 6.06 | 6.18 | 6.09 | 6.25 | 6.14 |
| 13 | 5.21 | 6.14 | 5.54 | 6.11 | 6.18 | 6.17 | 6.28 | 6.16 |

*T2. Rise from benchmark to final, split into my own picks and the others' picks*

| league | seat | benchmark | final | jumps at my picks | drift while others pick | drift, positive part | drift, negative part | final minus last solve |
|---|---|---|---|---|---|---|---|---|
| 252098 | 10 | 4.87 | 5.21 | -0.03 | 0.36 | 0.42 | -0.06 | 0.00 |
| 31153 | 9 | 5.32 | 6.14 | 0.13 | 0.69 | 0.73 | -0.04 | 0.00 |
| 224319 | 6 |  | 5.54 | 0.01 | 0.51 | 0.53 | -0.02 | 0.00 |
| 258332 | 7 | 5.38 | 6.11 | 0.15 | 0.58 | 0.58 | 0.00 | 0.00 |
| 223259 | 5 | 5.45 | 6.08 | 0.09 | 0.65 | 0.65 | 0.00 | -0.10 |
| 230585 | 10 | 5.47 | 6.17 | 0.06 | 0.65 | 0.69 | -0.04 | 0.00 |
| 225248 | 6 | 5.53 | 6.28 | 0.08 | 0.68 | 0.75 | -0.08 | 0.00 |
| 258901 | 11 | 5.51 | 6.16 | 0.16 | 0.49 | 0.49 | 0.00 | 0.00 |

Single-opponent-pick steps across the eight drafts: n 1002, mean +0.0043, 5th and 95th percentile -0.046 / +0.053, steps below -0.01: 214, above +0.01: 330.

**(a) The opponent model.** The curve is fixed at the attach, so it contributes nothing to the rise.
Across curves it matters: the same final rosters score 5.96 on their session curves, 5.74 on the
simulated league's curve and 6.32 on a curve fitted to the room's twelve rosters, and beat 6.31
categories against the room itself (T3). The rooms are weaker and narrower than the curve assumed:
the room's mean sits below the session curve's in field-goal percentage, rebounds, steals,
blocks and turnovers and its spread is 0.82 to 0.99 of the session's (mean 0.88, T4). 252098, whose curve came
from the simulated league because the archive was empty, has the widest sigmas and the smallest
rise. The error in the opponent model understated the finals; it did not create the rise.

*T3. The final roster scored on three curves and against the room (all on BBM z)*

| league | seat | session curve | simulated curve | room curve (11 opp.) | room, cats beaten | best opponent, cats beaten | rank of 12 | matchups of 11 | secured | conceded |
|---|---|---|---|---|---|---|---|---|---|---|
| 252098 | 10 | 5.21 | 5.25 | 5.19 | 5.27 | 5.36 | 3 | 11 | 5 | 3 |
| 31153 | 9 | 6.14 | 6.10 | 6.83 | 7.00 | 5.45 | 1 | 11 | 1 | 1 |
| 224319 | 6 | 5.54 | 5.40 | 5.88 | 5.82 | 5.45 | 1 | 10 | 1 | 1 |
| 258332 | 7 | 6.11 | 5.94 | 6.40 | 6.45 | 5.09 | 1 | 11 | 2 | 0 |
| 223259 | 5 | 6.08 | 5.79 | 6.07 | 5.73 | 5.27 | 1 | 10 | 1 | 1 |
| 230585 | 10 | 6.17 | 5.79 | 6.87 | 6.91 | 5.82 | 1 | 11 | 2 | 1 |
| 225248 | 6 | 6.28 | 5.95 | 6.78 | 6.73 | 5.36 | 1 | 11 | 2 | 1 |
| 258901 | 11 | 6.16 | 5.72 | 6.55 | 6.55 | 5.45 | 1 | 10 | 3 | 1 |

*T4. Session curve (mean over the eight sessions) against a curve fitted to each room's twelve drafted rosters*

| category | session mean | room mean | session sigma | room sigma | ratio |
|---|---|---|---|---|---|
| fg_pct | -0.45 | -0.71 | 3.77 | 3.31 | 0.88 |
| ft_pct | 0.03 | 0.06 | 4.08 | 3.92 | 0.96 |
| threes | -0.40 | -0.41 | 3.89 | 3.31 | 0.85 |
| pts | 0.09 | 0.24 | 3.19 | 2.57 | 0.82 |
| reb | -0.58 | -0.72 | 3.20 | 2.66 | 0.83 |
| ast | 0.59 | 0.95 | 3.32 | 2.77 | 0.86 |
| stl | -1.06 | -1.31 | 4.11 | 4.06 | 0.99 |
| blk | -0.58 | -0.72 | 3.77 | 3.36 | 0.90 |
| tov | -0.89 | -1.33 | 3.77 | 3.24 | 0.87 |

**(b) Did targets survive longer than modelled?** No. The plan's own targets were taken earlier
than the model expected (section 2, T18), so the rise is not re-optimisation gains from targets
lasting. Re-planning onto other players produced it, and the benchmark values those players at the
replacement level by construction: a lost target is replaced by a replacement-level fill with no
recourse.

**(c) The discount collapsing.** The re-solve (T16, T17) measures this directly. The pick-1 plan
is worth 5.47 at modelled odds and 6.07 with every target obtained: a discount of 0.60, against a
realised rise from benchmark to final of 0.66 (the seven drafts with a benchmark) and a mean final
of 5.96. The discount is still 0.39 at round 5, 0.14 at round 10 and zero at the last pick, as the
planned targets become the picks already made; the final lands within 0.1 of the undiscounted
first plan (the 2026-09-22 mock study: within 0.4). The pick-1 plan scored against the final room
(its players summed, opponents as they finished) beats 6.40 categories where the final roster
beats 6.31, and on the room curve it is worth 6.18 against the final's 6.32: the draft neither
gained nor lost against the first plan under BBM. Only 4.6 of the thirteen planned names per draft
ended up on the roster.

*T16. The re-solved pick-1 plan: the benchmark's availability discount, and the plan against the final room*

| league | pick-1 plan, modelled odds | same plan, every target obtained | discount | realised final | pick-1 plan on the room curve | pick-1 plan vs the room, cats beaten | planned players on the final roster |
|---|---|---|---|---|---|---|---|
| 252098 | 5.25 | 6.05 | 0.80 | 5.21 | 5.99 | 6.64 | 2 |
| 31153 | 5.41 | 6.19 | 0.78 | 6.14 | 6.60 | 7.00 | 5 |
| 224319 | 5.48 | 6.21 | 0.73 | 5.54 | 6.35 | 6.45 | 5 |
| 258332 | 5.52 | 6.19 | 0.68 | 6.11 | 6.33 | 6.55 | 5 |
| 223259 | 5.54 | 6.12 | 0.58 | 6.08 | 5.98 | 5.91 | 7 |
| 230585 | 5.49 | 5.89 | 0.41 | 6.17 | 6.25 | 6.45 | 5 |
| 225248 | 5.53 | 5.95 | 0.41 | 6.28 | 5.97 | 6.00 | 4 |
| 258901 | 5.51 | 5.92 | 0.41 | 6.16 | 5.96 | 6.18 | 4 |

*T17. The discount by round (means over the leagues re-solved)*

| round | plan at modelled odds | plan with every target obtained | discount | mean odds of a planned target |
|---|---|---|---|---|
| 1 | 5.467 | 6.065 | 0.599 | 0.835 |
| 2 | 5.499 | 5.948 | 0.448 | 0.845 |
| 3 | 5.540 | 5.988 | 0.448 | 0.824 |
| 4 | 5.532 | 5.955 | 0.424 | 0.818 |
| 5 | 5.587 | 5.971 | 0.385 | 0.802 |
| 6 | 5.643 | 6.037 | 0.394 | 0.785 |
| 7 | 5.702 | 6.031 | 0.329 | 0.777 |
| 8 | 5.758 | 6.068 | 0.309 | 0.750 |
| 9 | 5.782 | 6.019 | 0.236 | 0.779 |
| 10 | 5.821 | 5.959 | 0.138 | 0.813 |
| 11 | 5.900 | 5.968 | 0.068 | 0.861 |
| 12 | 5.938 | 5.973 | 0.034 | 0.870 |
| 13 | 5.974 | 5.975 | 0.000 | 1.000 |

**Freezing one dimension at a time.** Final roster on the pick-1 opponent model: the session-curve
column of T3 (the model never changed). Pick-1 plan against the final opponents: T16. Final roster
on the room's opponents: T3. Every freeze lands between 5.2 and 6.9, and the one that moves the
number most is the choice of curve, not the draft.

## 2. Calibration

**Availability at our next pick.** Over 6774 uncertain board cases the model gave 0.618 where
0.656 survived: conservative overall, as the 2026-09-23 study found in simulation. The error has a
sign that depends on BBM's view of the player (T5). Players whose BBM rank is at least ten places
better than their ADP survived 0.48 where the model said 0.60 (1598 cases); the rest survived 0.71
where it said 0.62 (5176). The gap opens from ADP 49 and is widest at ADP 97 to 120, where the
league table takes over from the formula: -0.17 for the favourites, +0.11 for the rest.

*T5. Availability model (ADP formula below 90, league table from 90) at my picks: modelled against realised survival, uncertain cases only (0.02 < p < 0.98)*

| ADP | player | n | modelled | realised | realised minus modelled |
|---|---|---|---|---|---|
| 1-24 | BBM rank 10+ better than ADP | 18 | 0.519 | 0.333 | -0.186 |
| 1-24 | the rest | 203 | 0.508 | 0.532 | 0.024 |
| 121-156 | BBM rank 10+ better than ADP | 73 | 0.741 | 0.808 | 0.068 |
| 121-156 | the rest | 189 | 0.693 | 0.810 | 0.116 |
| 25-48 | BBM rank 10+ better than ADP | 104 | 0.500 | 0.490 | -0.010 |
| 25-48 | the rest | 301 | 0.493 | 0.518 | 0.026 |
| 49-72 | BBM rank 10+ better than ADP | 227 | 0.491 | 0.410 | -0.081 |
| 49-72 | the rest | 396 | 0.482 | 0.528 | 0.046 |
| 73-96 | BBM rank 10+ better than ADP | 420 | 0.534 | 0.426 | -0.108 |
| 73-96 | the rest | 584 | 0.519 | 0.522 | 0.003 |
| 97-120 | BBM rank 10+ better than ADP | 756 | 0.680 | 0.508 | -0.172 |
| 97-120 | the rest | 3503 | 0.668 | 0.783 | 0.114 |

**Where the room takes BBM's favourites.** The room's own picks (ours excluded, ADP 1 to 96, T6)
show why: players BBM ranks far above their ADP went 7.9 picks before it on average, and players
BBM ranks far below went 5.5 picks after. Issue #70's premise, that BBM favourites outlast ADP and
so make the benchmark low, is the wrong way round in these rooms. The benchmark is low because of
its construction, not because the targets lasted. Either the ADP is stale against the news BBM has
already priced, or these rooms contain other drafters using the same or similar projections.

*T6. Where the room took players relative to their Yahoo ADP, by BBM's view of them (our own picks excluded)*

| BBM rank vs ADP | room's picks, ADP 1-96 | mean pick minus ADP | median |
|---|---|---|---|
| BBM rank 30+ worse than ADP | 162 | 5.5 | 2.9 |
| BBM rank 10 to 30 worse | 102 | 1.5 | 0.7 |
| within 10 places | 247 | -0.4 | -0.4 |
| BBM rank 10 to 30 better | 146 | -1.5 | -1.4 |
| BBM rank 30+ better than ADP | 38 | -7.9 | -7.4 |

**The plan's own targets.** The re-solved plans give each planned player his modelled odds of
lasting to his planned pick (T18). Realised survival falls below modelled at every horizon, and the
further ahead the pick the worse: 7 points short within one round, 17 within two, 23 to 27
beyond. Over all 624 planned targets the model said 0.78 and 0.57 lasted. The plan's later rounds
are built on names that will not be there, which is what the 2026-09-22 mock study saw with 24
percent of the first plan's names on the final roster.

*T18. The plan's own targets: modelled against realised survival to the planned pick, by how far ahead the pick was*

| picks ahead | n | modelled | realised | realised minus modelled |
|---|---|---|---|---|
| 1-12 | 48 | 0.925 | 0.854 | -0.070 |
| 13-24 | 136 | 0.853 | 0.684 | -0.169 |
| 25-48 | 152 | 0.808 | 0.553 | -0.256 |
| 49-96 | 208 | 0.748 | 0.514 | -0.234 |
| 97+ | 80 | 0.630 | 0.362 | -0.267 |

## 3. Cross-system check

**Categories beaten, rank and matchups under seven scorings** (T7 to T10). Under BBM our seat is
first in seven rooms and third in 252098 (the room with the simulated curve), with 10.6 matchups of
11 won in projection and a best opponent at 5.4 categories. Under the three projection systems and
their consensus the same rosters beat 4.75 to 4.97 categories, rank 3.8 to 5.3 and win 6.9 to 7.9
matchups: a good roster, not a dominant one. Last season's actual stats, which are not a projection
but are the one source outside every projection system's assumptions, put us at 5.5 categories and
rank 4, with four rooms (230585, 258332, 258901 and 31153) in the top four under every scoring.

*T7. Our final roster under each system: categories beaten of 9 (mean over 11 opponents)*

| league | BBM | Yahoo proj. | ESPN proj. | FantasyPros | consensus of 3 | 2025-26 actual (Yahoo) | 2025-26 actual (ESPN) |
|---|---|---|---|---|---|---|---|
| 223259 | 5.73 | 5.00 | 4.91 | 4.82 | 4.91 | 3.64 | 3.73 |
| 224319 | 5.82 | 4.64 | 3.91 | 3.73 | 4.00 | 4.55 | 4.73 |
| 225248 | 6.73 | 4.18 | 4.45 | 4.45 | 4.00 | 5.18 | 5.18 |
| 230585 | 6.91 | 4.91 | 5.73 | 5.45 | 5.18 | 6.45 | 6.36 |
| 252098 | 5.27 | 4.82 | 5.09 | 5.00 | 4.91 | 5.45 | 5.45 |
| 258332 | 6.45 | 5.45 | 5.00 | 4.36 | 5.09 | 7.09 | 7.09 |
| 258901 | 6.55 | 5.00 | 5.27 | 5.00 | 5.09 | 6.55 | 6.64 |
| 31153 | 7.00 | 4.55 | 5.36 | 5.18 | 5.18 | 5.36 | 4.82 |

*T8. Rank of 12 by categories beaten*

| league | BBM | Yahoo proj. | ESPN proj. | FantasyPros | consensus of 3 | 2025-26 actual (Yahoo) | 2025-26 actual (ESPN) |
|---|---|---|---|---|---|---|---|
| 223259 | 1 | 4 | 3 | 4 | 3 | 11 | 10 |
| 224319 | 1 | 4 | 12 | 12 | 11 | 6 | 5 |
| 225248 | 1 | 9 | 6 | 8 | 11 | 4 | 4 |
| 230585 | 1 | 3 | 2 | 3 | 3 | 1 | 1 |
| 252098 | 3 | 4 | 2 | 4 | 3 | 4 | 4 |
| 258332 | 1 | 2 | 2 | 7 | 2 | 1 | 1 |
| 258901 | 1 | 3 | 2 | 2 | 3 | 1 | 1 |
| 31153 | 1 | 5 | 1 | 2 | 2 | 4 | 6 |

*T9. Matchups won of 11*

| league | BBM | Yahoo proj. | ESPN proj. | FantasyPros | consensus of 3 | 2025-26 actual (Yahoo) | 2025-26 actual (ESPN) |
|---|---|---|---|---|---|---|---|
| 223259 | 10 | 7 | 7 | 7 | 7 | 2 | 3 |
| 224319 | 10 | 5 | 3 | 2 | 4 | 5 | 6 |
| 225248 | 11 | 5 | 5 | 5 | 3 | 7 | 7 |
| 230585 | 11 | 8 | 10 | 9 | 9 | 11 | 11 |
| 252098 | 11 | 9 | 11 | 10 | 10 | 10 | 10 |
| 258332 | 11 | 10 | 8 | 5 | 8 | 11 | 11 |
| 258901 | 10 | 7 | 9 | 8 | 9 | 10 | 10 |
| 31153 | 11 | 6 | 10 | 9 | 8 | 7 | 6 |

*T10. Means over the eight leagues*

| system | cats beaten | rank | matchups | best opponent |
|---|---|---|---|---|
| BBM | 6.31 | 1.25 | 10.62 | 5.43 |
| Yahoo proj. | 4.82 | 4.25 | 7.12 | 5.70 |
| ESPN proj. | 4.97 | 3.75 | 7.88 | 5.38 |
| FantasyPros | 4.75 | 5.25 | 6.88 | 5.42 |
| consensus of 3 | 4.80 | 4.75 | 7.25 | 5.49 |
| 2025-26 actual (Yahoo) | 5.53 | 4.00 | 7.88 | 6.00 |
| 2025-26 actual (ESPN) | 5.50 | 4.00 | 8.00 | 6.06 |

**Agreement between systems.** The projection systems agree with BBM on the drafted players' order
at rank correlation 0.80 to 0.88, and the two actuals sources at 0.55 (T11). The disagreement that
matters is concentrated in the players we own (section 4).

*T11. Rank correlation of total z with BBM over the drafted players (mean of eight leagues)*

| system | rank correlation with BBM |
|---|---|
| consensus of 3 | 0.871 |
| 2025-26 actual (ESPN) | 0.552 |
| ESPN proj. | 0.840 |
| FantasyPros | 0.801 |
| 2025-26 actual (Yahoo) | 0.561 |
| Yahoo proj. | 0.875 |

**Rates or games?** BBM's edge over the consensus is 1.5 categories on these rosters. Swapping the
games projections between systems (T12) moves about 0.4 of it: BBM's per-game rates with the
consensus' games still beat 5.9; the consensus' rates with BBM's games beat 5.2. BBM's view of
minutes and production, not its injury or games model, carries most of the difference.

*T12. Rates against games: the same rosters with per-game rates and games projections swapped between BBM and the consensus (means)*

| variant | cats beaten | rank | matchups |
|---|---|---|---|
| BBM | 6.31 | 1.25 | 10.62 |
| BBM rates, 70 games each | 5.89 | 1.50 | 10.00 |
| BBM rates, consensus games | 5.90 | 1.25 | 10.00 |
| consensus | 4.80 | 4.75 | 7.25 |
| consensus rates, 70 games each | 4.73 | 4.88 | 6.50 |
| consensus rates, BBM games | 5.18 | 3.00 | 8.50 |

## 4. Optimizer's curse

**Where our picks sit against the market** (T13, T14). Our picks went at their Yahoo ADP on
average (ADP minus pick -0.1) where the room reached 4.4 picks early, so by the market's clock we
paid a fair price. By BBM's rank we took players 22 places below their ADP; the room took players
18 places above. Half of our picks were players BBM ranked twenty or more places better than their
ADP (the room: 13 percent); only one in ten of ours was a player BBM ranked below his ADP (the room:
53 percent). From round 4 on our picks averaged 22 to 33 places of BBM-versus-market gap in every phase.
On the same players BBM's z is 1.0 above the consensus' for our picks and 0.2 below for the room's.

*T13. Market and rank gaps of our picks against the room's (means; a positive 'minus pick' is a player taken before his ADP or rank)*

| picks | Yahoo ADP minus pick | Yahoo rank minus pick | ESPN ADP minus pick | BBM rank minus pick | ADP minus BBM rank | FantasyPros rank minus BBM rank | BBM z minus consensus z |
|---|---|---|---|---|---|---|---|
| our 104 picks | -0.1 | 9.0 | 10.8 | -21.9 | 22.2 | 54.6 | 1.0 |
| the room's 1144 | -4.4 | 1.7 | 3.9 | 14.4 | -18.5 | -4.9 | -0.2 |

*T14. The same by phase of the draft*

| rounds | picks | Yahoo ADP minus pick | BBM rank minus pick | ADP minus BBM rank | FantasyPros rank minus BBM rank |
|---|---|---|---|---|---|
| rounds 1-3 | ours | 4.8 | 0.3 | 4.5 | 13.6 |
| rounds 1-3 | the room's | 1.3 | 10.5 | -9.3 | 3.7 |
| rounds 4-6 | ours | 11.3 | -18.3 | 29.6 | 51.2 |
| rounds 4-6 | the room's | 1.1 | 8.6 | -7.5 | 4.0 |
| rounds 7-9 | ours | 5.9 | -27.1 | 33.0 | 73.1 |
| rounds 7-9 | the room's | 1.3 | 15.1 | -13.8 | -6.6 |
| rounds 10-13 | ours | -17.4 | -37.5 | 21.9 | 74.0 |
| rounds 10-13 | the room's | -18.0 | 21.3 | -38.5 | -17.3 |

**Concentration.** 49 distinct players cover our 104 picks; nine of them (Aaron Nesmith on seven
rosters, Collin Murray-Boyles six, VJ Edgecombe and Jakob Poeltl five, Cam Johnson, Paul Reed,
Nickeil Alexander-Walker, Kevin Durant and Kawhi Leonard four) fill 43 picks. On those nine BBM
is 1.6 z above the consensus and above it in 91 percent of cases; their ADP sits 30 places below
BBM's rank of them, and we took them 3 picks after their ADP. This is the selection the curse
predicts: a solver that maximises a single system's z over 156 players and 13 slots owns the
players that system likes most relative to its peers, and the rosters where those players cluster
(225248 with eight of the nine, 230585 with seven) are the ones that rank first under BBM and
mid-table or last under the others.

**Shrinkage** (T15). Our rosters re-scored with BBM z shrunk toward another system keep the first
rank in seven of eight rooms at 25 percent, five at 50, two at 75 and none at 100 toward the
consensus; toward the market prior the roster holds up to 50 percent and collapses at 100 (the
prior scores every player at his ADP neighbourhood's mean, which erases player selection
altogether). This is a robustness test of the claimed edge, not a draft under shrunk projections,
which would have taken other players.

*T15. Our roster as BBM z is shrunk toward another system (categories beaten / rank of 12 / leagues where we stay first; means over eight leagues)*

| shrunk toward | 0%: cats / rank / 1st | 25%: cats / rank / 1st | 50%: cats / rank / 1st | 75%: cats / rank / 1st | 100%: cats / rank / 1st |
|---|---|---|---|---|---|
| consensus of 3 | 6.31 / 1.2 / 7 | 6.00 / 1.2 / 7 | 5.61 / 1.6 / 5 | 5.19 / 2.6 / 2 | 4.80 / 4.8 / 0 |
| Yahoo proj. | 6.31 / 1.2 / 7 | 5.92 / 1.2 / 7 | 5.52 / 1.9 / 4 | 5.17 / 2.8 / 2 | 4.82 / 4.2 / 0 |
| ESPN proj. | 6.31 / 1.2 / 7 | 6.03 / 1.2 / 7 | 5.68 / 1.2 / 6 | 5.34 / 2.2 / 4 | 4.97 / 3.8 / 1 |
| FantasyPros | 6.31 / 1.2 / 7 | 6.02 / 1.1 / 7 | 5.62 / 1.4 / 6 | 5.20 / 2.4 / 2 | 4.75 / 5.2 / 0 |
| market (ADP-neighbourhood mean z) | 6.31 / 1.2 / 7 | 6.22 / 1.2 / 7 | 6.00 / 1.4 / 7 | 5.53 / 2.6 / 3 | 2.31 / 10.8 / 0 |

**The market drafter in our seat** (T20, T21). The honest benchmark for a seat is what the seat
gives for free: the best player by Yahoo's rank at each of our picks, everything else unchanged.
That roster beats 4.45 categories under BBM (rank 7) and 4.7 under the consensus (rank 5). Ours
beats it by 1.85 categories under BBM, by 0.06 to 0.42 under the projection systems, and by 0.8
under last season's actuals. The 0.8 under the actuals is the one piece of evidence outside BBM
that the selection is not pure noise; the 0.06 under FantasyPros and 0.09 under the consensus say
that under the market's own view the draft bought almost nothing beyond the seat.

*T20. The market drafter's roster in our seat (best remaining Yahoo rank at each of our picks, the room's picks unchanged) against ours, under each system (means over eight leagues)*

| scored under | market roster, cats beaten | market roster, rank | our roster, cats beaten | our roster, rank | our roster minus market roster |
|---|---|---|---|---|---|
| BBM | 4.45 | 7.00 | 6.31 | 1.25 | 1.85 |
| Yahoo proj. | 4.74 | 5.38 | 4.82 | 4.25 | 0.08 |
| ESPN proj. | 4.55 | 6.75 | 4.97 | 3.75 | 0.42 |
| FantasyPros | 4.69 | 5.62 | 4.75 | 5.25 | 0.06 |
| consensus of 3 | 4.70 | 5.25 | 4.80 | 4.75 | 0.09 |
| 2025-26 actual (Yahoo) | 4.70 | 6.12 | 5.53 | 4.00 | 0.83 |
| 2025-26 actual (ESPN) | 4.70 | 5.88 | 5.50 | 4.00 | 0.80 |

*T21. The same per league, BBM and consensus (categories beaten of 9)*

| league | market roster, BBM | ours, BBM | market roster, consensus | ours, consensus |
|---|---|---|---|---|
| 223259 | 4.91 | 5.73 | 4.55 | 4.91 |
| 224319 | 4.09 | 5.82 | 4.00 | 4.00 |
| 225248 | 4.91 | 6.73 | 4.82 | 4.00 |
| 230585 | 4.00 | 6.91 | 4.64 | 5.18 |
| 252098 | 5.00 | 5.27 | 5.09 | 4.91 |
| 258332 | 4.27 | 6.45 | 4.73 | 5.09 |
| 258901 | 4.27 | 6.55 | 5.27 | 5.09 |
| 31153 | 4.18 | 7.00 | 4.55 | 5.18 |

**The contrasts.** The points league 238174 rose from 0.32 to 0.97 expected wins of one category
with the same mechanics. The keeper league 31822 (ten teams, seat 4, keepers, the ADP formula alone
for availability, BBM projections and the simulated curve of 2026-09-21) fell from a benchmark of
5.14 to a final of 4.26 and ranks fourth of ten against its room: the rise is not universal, and
that draft is not analysed further here.

## 5. Recommendation

The rise is not a measure of anything and should stop being read as one. The edge is real under BBM
and small under everything else; the season decides which view is right, and the draft tooling
should assume neither.

1. **Report bounds instead of a rise.** At pick 1 show the benchmark (the plan at modelled odds,
   the lower bound), the plan with every target obtained (the upper bound) and the market drafter's
   roster in our seat; at the end show the final against all three. The final landing between the
   two bounds is expected; the number to watch is the final against the market roster under a
   system other than BBM.
2. **Draft on a blend, not on BBM alone.** Shrink BBM 25 to 50 percent toward a consensus of Yahoo,
   ESPN and FantasyPros (equal weights until in-season errors give better ones). At 25 percent the
   BBM-scored cost on these rosters is 0.3 categories and the first rank holds in seven of eight;
   at 50 percent 0.7 and five of eight. The 2027 mock programme should test drafting on the blend
   against drafting on BBM, scored under every system, before the real drafts.
3. **Condition survival on the BBM-versus-market gap.** The league table and the formula overstate
   the survival of BBM favourites by 8 to 19 points from ADP 49 on and understate the rest by 5 to
   11. Key the table by ADP bucket and gap bucket, or use the better of ADP rank and BBM rank as
   the favourite's effective ADP, and re-check T5 after the next archive refit.
4. **Score per opponent.** The room curve is narrower than the session curve by 12 percent on
   average and the finals score 0.36 higher on it. The live-curve study's per-opponent fills
   (2026-10-19) remove the single-curve assumption; this audit adds the reason to prefer them.
5. **Keep the concentration visible.** When one player appears on more than half of the night's
   rosters, the dashboard should say so: it is the clearest live sign that a single system's view
   is being bought nine times over.

**The in-season test.** Record, every Monday from the first scoring week, for each of the eight
nine-category leagues (and 238174 for points):

- Per team: the week's nine category totals and games played, the matchup result (categories won,
  lost, tied) and the opponent; the season-to-date standings rank.
- Per team: the season-to-date nine category totals, from which categories beaten against all
  eleven opponents is computed exactly as this audit computes it from projections.
- Per drafted player (the 156 of each league): games played and season-to-date totals in the
  twelve stat columns, so each system's projection error can be measured on the same pool.
- The market drafter's counterfactual roster per league (its thirteen players are known) and its
  season-to-date totals from the same player lines.

From these, three statistics decide the question. First, across the 96 drafted teams, which
system's draft-day categories beaten best predicts realised categories beaten (rank correlation,
by week); if BBM leads, the edge was real. Second, our realised categories beaten against the
market roster's, league by league; the 1.85 under BBM and the 0.1 under the consensus are the two
predictions, and the realised gap falls somewhere between. Third, on the 49 players we own,
realised z against BBM's and the consensus' projections; the curse predicts BBM's error on those
players is larger and signed toward the consensus. Eight leagues over twenty weeks is enough to
separate 1.85 from 0.1; it is not enough to separate 0.5 from 0.1, so the shrinkage weight for 2027
should come from the first statistic rather than the second.

## Caveats

- Eight drafts, one weekend, one set of BBM projections (2026-10-18 and 2026-10-19) and Yahoo ADP
  as of each draft. Nothing here is a season result.
- The re-solve uses the league survival table as it stands on 2026-10-20 (6.5 drafts), not as it
  stood during each draft, and a copy of each session's curve. It reproduces the live first pick
  on two boards in three (31 percent in 252098, which drafted on the simulated survival table, to
  92 percent in 230585) and the live expected wins within 0.07 on average (T19); the discount and
  the target calibration are offline estimates on those plans.
- Categories beaten and matchups are projections against projected rosters, including the
  opponents' open slots filled at replacement level. They measure the same thing as the objective
  with the room in place of the curve, no more.
- The outside systems cover the pool unevenly: FantasyPros 264 players, ESPN 700, Yahoo's
  projections every rostered player. Uncovered players take the replacement z, which slightly
  flattens late-round differences under FantasyPros.
- The shrinkage and market-roster tests re-score the rosters we drafted. A drafter using shrunk
  projections or Yahoo's rank from pick 1 would have changed the room's picks after ours as well.
- Last season's actuals are per-player totals for 2025-26, not a projection; rookies and players
  who missed the season take the replacement z under them.

## Reproduce

Scratch repository, `research/draft-edge-2026-10-20/`, run with the project venv and `-I`:
`01_trajectory.py`, `01b_steps.py`, `02_room.py` (section 1), `06_survival.py` (section 2),
`03_systems.py`, `03b_rates.py` (section 3), `04_market.py`, `04b_market_roster.py` (section 4),
`05_resolve.py` (the offline re-solve, about two minutes per league, in-process API with
`solve_ahead` off and a 20 s time limit), `07_plans.py` (T16 to T19), `08_tables.py` (every table
into `out/tables.md`) and `09_build_doc.py` (this document from `template.md`). Outside systems:
`data/external/README.md`.
