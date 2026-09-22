# Mock-draft study findings, 2026-09-22

Point-form summary. The full write-up with tables is
[2026-09-22-mock-study.md](2026-09-22-mock-study.md); the per-mock data, CSV tables and
`report.html` are in `data/studies/2026-09-22/` (not committed, built on subscriber projections).

## Setup

- 100 mocks, 12 teams, 13 rounds, nine categories, BBM rest-of-season projections of 2026-09-21.
- My team in every slot (1 to 12, cycling), always the rolling-horizon planner with automatic punt.
- Other eleven teams drew z-score, ADP or LP drafters at random each mock.
- Every mock branched at each of my picks with the punt frozen from there, same board and same
  random draws, so all comparisons are paired.

## Benchmark

- Final roster beats the plan value frozen at my first pick by +7.0 z, in 99% of mocks.
- The benchmark discounts every future pick by the odds of losing the player and never credits
  re-planning around who falls instead. It is a conservative gauge, not an efficiency score.
- Against the undiscounted first plan the final lands at -0.4. Only 24% of the names in the first
  plan end up on the roster.

## Punt drift

- Pick 1: BLK+TO in 77% of mocks. Last pick: 3PM+FT% in 78%.
- 86 of 100 drafts switched punt; 62 at pick 2, 18 at pick 3, none for the first time after pick 8.
- Cause: the punt scan runs the roster model, which assumes every undrafted player can be had.
  The flip is systematic, not noise.

## Freezing the punt from pick k

- Frozen from pick 2: +1.2 z over letting it float. Pick 3: +0.8. Pick 1: +0.3, not significant.
  Pick 4 and later: no difference.
- Drafts with two or more switches finish about 1 z lower than drafts with none or one.

## Slot and opponents

- Slot 1 to slot 12 is worth about 7 z (final 75.8 to 69.0). Slot 2 has the best benchmark.
- The opponent mix (how many LP or z-score teams) has no significant effect.
- Two or more LP opponents whose punt overlaps mine cost about 1.5 z, on a small sample.
- Finished-roster value: me 71.8, LP 57.6, z-score 52.6, ADP 40.3. I lead the league in 89 of 100.

## Reading the other teams

- ADP drafters: 91% recognised after three rounds.
- LP drafters with a punt: 67% after five rounds, 84% after the draft. A no-punt LP team looks
  exactly like a z-score team.
- The weakest category of an LP team's roster is its punt 51% of the time at round five, 90% at
  the end.
- LP teams take my planned players four times as often as ADP teams and 2.5 times as often as
  z-score teams; 72% of the LP snipes come from a team sharing my punt.
- Availability odds are calibrated overall but wrong per player: names the model ranks eleven or
  more places above BBM's rank are taken more often than predicted (Castle, Ighodaro, Green,
  Banchero, Randle).

## Value is not category wins

- 4.56 of nine categories won per matchup despite the top value rank: a coin flip.
- REB 95%, FG% 82%, BLK 77%; the two punted categories are gone; PTS, AST, STL and TO all sit
  near 40 to 50%.
- The sum-of-z objective piles surplus into categories already won (FG% total averages +13.8 z).
- BLK+TO rosters win 4.9 categories, 3PM+FT% rosters 4.5.

## Do next

1. Choose the punt with the availability-weighted horizon model, not the roster model.
2. Pin the punt after pick 2 by default.
3. Try a category-win objective, or the existing balance floor; the harness now reports
   categories won.
4. Blend ADP with the model's own rank in the availability odds.
5. Add a planner-strength opponent to the simulator.
6. Fix the ADP source before the live draft (with BBM rank as ADP, Embiid goes at pick 14 while
   the model ranks him 99th on season totals).

## Rerun

```bash
python scripts/mock_study.py --mocks 100 --out data/studies/<date> --workers 9
python scripts/mock_study_report.py data/studies/<date>
```
