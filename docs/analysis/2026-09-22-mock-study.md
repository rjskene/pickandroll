# Mock-draft study, 2026-09-22

How the rolling-horizon planner performs over 100 simulated 12-team drafts, and what the punt
strategy does along the way. Produced with `scripts/mock_study.py` (runs the drafts) and
`scripts/mock_study_report.py` (tables, charts, `report.html`). The per-mock JSON, the CSV
tables and the HTML report live in `data/studies/2026-09-22/`, which is not committed because
they are built on Basketball Monster subscriber projections; the aggregate numbers are below.

## Setup

- 12 teams, 13 rounds, Yahoo default lineup, nine categories, BBM rest-of-season per-game
  projections of 2026-09-21 converted to season totals. The export carries no ADP, so BBM's rank
  stands in for ADP in the availability model.
- My team drafts from every slot (1 to 12, cycling; slots 1 to 4 get nine mocks, the rest eight)
  with the rolling-horizon planner and automatic punt choice (up to two punts, balance 0).
- The other eleven teams each draw a drafter uniformly at random from z-score (softmax over the
  top 15 by total z, noise 1.0), ADP (private noisy board) and LP (their own roster MILP with a punt
  drawn from the weighted list in `draft/autopick.py`).
- Every mock is branched at each of my picks k = 1..12: the picks before k are replayed and the
  punt the auto run chose at pick k is held for the rest of the draft. Branch 1 is "punt fixed from
  the first pick". All random draws are keyed by (seed, overall pick), so a branch and the auto run
  differ only through the players on the board. 100 auto drafts plus 1200 branches took 27 minutes
  on nine cores.
- Scores are the planner's own scale: z above replacement level summed over the active categories
  of the finished roster, under whichever punt suits the roster best. "Benchmark" is the plan
  objective the moment I am on the clock for my first pick.

## 1. Final team vs the benchmark at my first pick

| | auto punt | punt fixed at pick 1 |
|---|---|---|
| final minus benchmark, mean (95% CI) | +6.96 (±0.64) | +7.24 (±0.47) |
| mocks at or above the benchmark | 99% | 100% |
| mean benchmark / mean final | 64.8 / 71.8 | 64.8 / 72.0 |

The benchmark is conservative by construction: every later pick in the plan is discounted by the
odds of losing the player, and the discount is never recovered in the objective even though a lost
player is replaced by whoever falls instead. Against the undiscounted first plan (worth 72.1 on
average if every named player fell to me) the finished roster lands at -0.39 (±0.69), and only
24% of the names in the first plan end up on the roster. So "vs benchmark" works as a running gauge against the
first plan, not as an efficiency score; the branches and slots are the fair comparisons.

By slot (auto punt):

| slot | mocks | benchmark | final | final − bench | rank | switches |
|---|---|---|---|---|---|---|
| 1 | 9 | 66.9 | 75.8 | 8.9 | 1.1 | 1.6 |
| 2 | 9 | 69.3 | 76.1 | 6.8 | 1.0 | 1.1 |
| 3 | 9 | 66.1 | 72.6 | 6.5 | 1.0 | 1.1 |
| 4 | 9 | 66.1 | 73.3 | 7.2 | 1.0 | 1.4 |
| 5 | 8 | 64.7 | 72.9 | 8.2 | 1.0 | 1.4 |
| 6 | 8 | 64.1 | 71.4 | 7.3 | 1.4 | 1.8 |
| 7 | 8 | 63.9 | 71.1 | 7.1 | 1.4 | 2.1 |
| 8 | 8 | 63.6 | 70.3 | 6.7 | 1.0 | 1.9 |
| 9 | 8 | 63.2 | 68.5 | 5.4 | 1.0 | 1.5 |
| 10 | 8 | 62.7 | 69.3 | 6.6 | 1.1 | 1.3 |
| 11 | 8 | 63.0 | 69.6 | 6.6 | 1.3 | 1.1 |
| 12 | 8 | 62.9 | 69.0 | 6.1 | 1.3 | 0.8 |

## 2. How the punt changed over the draft

- At the first pick the scan chose BLK+TO in 77 mocks, TO+FG% in 11, TO in 10. At the last pick
  78 mocks were on 3PM+FT%, 12 on BLK+TO, 7 on TO+FG%, 3 on TO+FT%.
- 86 of 100 drafts switched at least once (mean 1.4 switches, 2.3 distinct punts). The first
  switch came at pick 2 in 62 drafts, pick 3 in 18, pick 4 in 5, pick 5 in 1. Switch rate by pick:
  62% at pick 2, 43% at 3, 20% at 4, 4 to 5% at picks 5 to 7, none after pick 9.
- The scan margin between the best punt and the runner-up is 0.75 z at pick 1, 1.1 at pick 2,
  2.3 at 3, 3.9 at 4, 5.0 at 5 and keeps growing: the punt is a near-tie at the first pick and
  settled by the fifth. When a switch happened the abandoned punt trailed by a median 1.9 z.
- The most common moves: BLK+TO to 3PM+FT% (38), BLK+TO to TO+FG% (24), TO+FT% to 3PM+FT% (21),
  TO+FG% to 3PM+FT% (16).
- Why: the punt scan runs the roster model, which assumes every undrafted player can be had. At
  pick 1 that favours a guard-heavy BLK+TO roster; once the guards go and the big men keep falling,
  the horizon plan prefers 3PM+FT%.

| switches | mocks | final − bench | final |
|---|---|---|---|
| 0 | 14 | 7.29 | 71.6 |
| 1 | 47 | 7.36 | 72.3 |
| 2 | 26 | 6.30 | 71.4 |
| 3+ | 13 | 6.51 | 70.8 |

## 3. Score if the punt had been fixed from pick k

Paired against the auto run (100 mocks each; "better/worse" = share of mocks).

| held from pick | final | gain vs auto | ±95% | better | worse | cats won of 9 |
|---|---|---|---|---|---|---|
| 1 | 72.0 | +0.28 | 0.63 | 45% | 39% | 4.92 |
| 2 | 73.0 | +1.19 | 0.59 | 39% | 17% | 4.89 |
| 3 | 72.6 | +0.81 | 0.56 | 17% | 7% | 4.66 |
| 4 | 71.7 | -0.04 | 0.28 | 4% | 4% | 4.57 |
| 5 to 8 | 71.7 to 71.8 | ±0.1 | | | | 4.56 |
| 9 to 12 | 71.8 | 0.00 | | 0% | 0% | 4.56 |
| auto | 71.8 | | | | | 4.56 |

An oracle choosing the best freeze point per mock would gain +2.45 (±0.59); the best run was auto
in 45 mocks, fixed at pick 1 in 27, pick 2 in 16, pick 3 in 8.

## 4. Draft position and the other drafters

- Slot is worth about seven z between the top and the bottom of the order (benchmark 66.9 to 62.9,
  final 75.8 to 69.0). Slot 2 has the highest benchmark (69.3).
- Final minus benchmark shows no significant effect of slot or of the opponent mix: OLS on the
  number of LP opponents (-0.28 per team, t = -1.0), z-score opponents (-0.29, t = -1.2), mid
  slots (-0.07) and late slots (-1.29, t = -1.6).
- Two or more LP opponents whose punt overlaps mine cost about 1.5 z against the benchmark (26
  mocks at 5.8 vs 7.5 with one and 7.6 with none); small samples.
- Finished-roster strength by drafter: me 71.8, LP 57.6, z-score 52.6, ADP 40.3. I lead the league
  in value in 89 of 100 mocks. Among LP opponents the TO+FT% (67.9) and TO (64.6) punts build the
  strongest rosters, AST (47.4) the weakest.

## 5. Reading the other teams, and who competes for my players

Multinomial logistic regression on per-team pick features (rank on the z board and the ADP board,
gap to the best available, consistency, roster category profile), trained on mocks 0 to 49, tested
on 50 to 99 (550 teams). Chance is 33%.

| rounds seen | accuracy | recall z | recall ADP | recall LP with punt | recall LP no punt |
|---|---|---|---|---|---|
| 2 | 59% | 23% | 84% | 71% | 65% |
| 3 | 66% | 36% | 91% | 72% | 67% |
| 5 | 69% | 50% | 97% | 67% | 44% |
| 9 | 79% | 68% | 99% | 76% | 50% |
| 13 | 85% | 81% | 100% | 84% | 50% |

- ADP drafters are obvious by round three. LP and z-score drafters both draft by value and stay
  confused until the roster's category profile gives an LP team's punt away. A no-punt LP team is a
  z-score team with lineup constraints and cannot be told apart.
- The weakest category of an LP team's roster is its punt 42% of the time after three rounds,
  51% after five, 68% after eight, 90% after the draft.
- Who takes the players my plan named for a later pick: LP teams 14.6 per 100 of their picks,
  z-score teams 5.7, ADP teams 3.6. Of the 712 planned players LP teams took, 511 went to a team
  whose punt overlaps the punt my plan was built on.
- Availability odds are calibrated overall (15% of planned players lost against 15% expected) but
  not per player: players the model ranks eleven or more places ahead of their ADP were available
  83% of the time against 87% predicted, players the model and the market agree on 89% against 80%.
  The names that keep disappearing (Stephon Castle, Oso Ighodaro, Jalen Green, Paolo Banchero,
  Julius Randle) are ones our z likes far more than BBM's rank does, taken by LP and z-score teams.

## 6. Value is not category wins

Comparing category totals (z summed over the roster) of my finished rosters with every opponent's:

| category | share of matchups won | my mean total z |
|---|---|---|
| REB | 95% | +8.6 |
| FG% | 82% | +13.8 |
| BLK | 77% | +5.2 |
| AST | 49% | +2.1 |
| PTS | 44% | -0.2 |
| TO | 41% | -3.2 |
| STL | 39% | -1.2 |
| 3PM | 15% | -11.5 |
| FT% | 14% | -15.4 |

4.56 of nine categories per matchup (4.3 against LP teams, 4.4 against z-score teams, 5.0 against
ADP teams) despite leading the league in value almost every time. The sum-of-z objective keeps
piling surplus into categories that are already won and leaves four coin flips. Rosters that held a
punt from pick one or two win 4.9; BLK+TO rosters win about 4.9 against 4.5 for 3PM+FT% rosters,
whichever way they were reached.

## Suggestions

1. Choose the punt with the availability-weighted horizon model rather than the roster model:
   short-list punts with the roster scan, re-price the top few with the plan. This removes the
   systematic flip from the pick-one punt to the pick-two punt.
2. Hold the punt after pick two (a pin-after-pick-two default, or require a margin of two z or so
   on the scan before switching from pick three on). Worth about +1.2 z per draft here, and it is
   what an oracle would do in most mocks.
3. Test a category-win objective: saturate each category's contribution once it clears the field,
   or use the existing balance floor; measure with the categories-won metric this harness now
   reports. Value rank and category wins disagree today.
4. Blend the ADP with the model's own rank in the availability odds, more strongly once value
   drafters are detected, so the players the model loves are not assumed to last.
5. Add a horizon-planner opponent to the simulator. The LP teams (57.6) are the strongest
   opponents but still 14 z behind the planner; a league of planners is the stress test.
6. Sanity-check the ADP source before the live draft: with BBM's rank as ADP, injury-discounted
   players such as Joel Embiid go at pick 14 to ADP teams while the model ranks them 99th on
   season totals. Yahoo ADP (once the API is approved) or a manual `data/adp.csv` fixes that.

## Rerunning

```bash
python scripts/mock_study.py --mocks 100 --out data/studies/<date> --workers 9
python scripts/mock_study_report.py data/studies/<date>
```

`--branches` limits the freeze points (empty for none); `--first-seed` continues a series. Runs
are resumable: mocks whose JSON already exists are skipped.
