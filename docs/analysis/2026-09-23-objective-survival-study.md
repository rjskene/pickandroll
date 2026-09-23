# Objective and availability study, 2026-09-23

Does the planner win more with a category-win objective (the "S-curve") instead of the sum of
z, and with simulated survival rates instead of the ADP formula? Overnight run of 2026-09-22 to
23: 3000 all-auto drafts for the survival table and league curve, then eight planner settings
through the same simulated leagues, 500 seeds for the four main conditions and 250 for the
rest. Per-mock data, CSV tables and `compare/report.html` are in `data/studies/2026-09-23/`
(not committed, built on subscriber projections). The round-leverage experiment (which rounds
the planner's pick is worth most) ran afterwards; its section is at the end.

## Findings

- **The S-curve wins matchups; the sum of z wins its own scoreboard.** Same leagues, same
  opponents: sum-of-z with a two-category punt wins 5.84 of 11 head-to-head matchups, the curve
  10.26 (ADP odds) or 10.28 (survival odds). Categories won per matchup 4.63 vs 5.50 to 5.52;
  roto points 60.0 vs 69.5 to 69.7. Paired by seed the curve is +4.4 matchups (95% CI ±0.23) and
  better in 92 to 93% of seeds. It finishes with 10 or 11 matchups won in 86% of drafts; the
  sum planner does in 8%.
- **Value and category wins pull apart.** The curve gives up 5.2 z of value against the sum
  planner under ADP odds, 2.3 z under survival odds, and is ranked first by value in 57 to 77%
  of leagues instead of 89%. Value is the sum planner's own objective; nothing else tracks it.
- **A punt is an outcome, not a goal.** The curve gets no punt and still concedes 2.8 categories
  on average (three in 80 to 84% of drafts): 3PM and FT% almost always, TO or PTS as the third.
  The sum planner's explicit two-punt scan concedes 2.4. The difference is where the surplus
  goes: the sum planner ends with FG% +14.6 z and REB +8.9 z (won 86% and 96% of the time) and
  coin flips on PTS, AST, STL and TO (41 to 51%); the curve ends with STL +4.9, AST +3.6 to
  +4.5, BLK +5, FG% +8.9 and wins AST 80 to 86%, STL 94 to 95%, BLK 87 to 91%, FG% 94 to 96%.
- **Punt width matters under the sum objective too.** One punt instead of two: +1.7 matchups
  (±0.36). No punt at all: +2.35 matchups while losing 14 z of value. Explicit punts were free
  only on the z scale.
- **Survival rates change nothing under the sum objective** (−0.08 matchups, ±0.19; value
  +0.37 ±0.23). Under the curve they recover value without touching wins: interaction +2.6 z
  (±0.6), share ranked first from 57% to 77%. The table is better calibrated than the formula
  (planned players available 92% realized vs 91% expected, Brier 0.07 against 0.11) and the
  gain lands on the specific later-round targets the curve leans on.
- **The curve's odds are conservative.** Expected categories won at pick one 5.01 to 5.06;
  realized 5.50 to 5.52. Re-planning against the real board adds about half a category, the
  same pattern the earlier study found for the value benchmark.
- **Sigma.** Halving sigma (steeper, all-or-nothing) loses: 9.69 matchups, value 64.9. Doubling
  it (flatter, closer to the plain sum) costs little: 10.04 matchups, value 70.1, rank-first
  82%, and it concedes less extreme totals. Real weeks are noisier than season totals, which
  argues for the flatter curve; take sigma at or above the league fit, not below.
- **Slot and opponents stop mattering.** The sum planner falls from 6.2 matchups in slots 1 to
  4 to 5.0 in slots 9 to 12 and from 6.7 with two or fewer LP opponents to 5.3 with five or more.
  The curve sits at 10.2 to 10.4 across slots and 10.1 to 10.4 across opponent mixes.
- **The curve drafts differently from pick one.** From slot 3 onward it takes Dyson Daniels
  first in 56 to 95% of drafts under ADP odds (36 to 73% under survival odds), ahead of Luka,
  Shai and Tatum, because elite steals are scarce and the bigs that win REB, BLK and FG% keep
  falling in these simulated drafts. Under survival odds it takes Jokic over Wembanyama at
  slot 1 (95%). Both are the optimizer reading the simulated opponents, and both are exactly
  the kind of choice to test against real draft data before trusting.
- **Cost.** Sum objective: 0.16 s per plan, 94 s per mock (the punt scan dominates). Curve: 8.8
  to 9.3 s per plan on a loaded core with the 80-candidate cap, hitting the 15 s limit in 3.9
  to 4.8 of 13 picks (picks one to five mostly), 122 to 129 s per mock. See "Cost" below.

## Setup

- Same simulated leagues as the 2026-09-22 study: 12 teams, 13 rounds, nine categories, BBM
  rest-of-season projections of 2026-09-21, my team cycling through slots 1 to 12, the other
  eleven teams drawing z-score, ADP or LP drafters at random with a punt of their own.
- Every condition drafts through the same seeds. A seed fixes the opponents, their drafters and
  punts, their private ADP boards and every random draw, so two conditions with the same seed
  differ only through my picks and what they do to the board. All comparisons are paired by
  seed with 95% confidence intervals.
- No branches this time (the punt-freeze question was answered on 2026-09-22).

## Conditions

| condition | objective | explicit punt | availability | seeds |
|---|---|---|---|---|
| sum-adp | sum of category z (the planner as studied on 2026-09-22) | scan, up to 2 | ADP formula | 500 |
| win-adp | category-win curve | none (the curve concedes on its own) | ADP formula | 500 |
| sum-surv | sum of category z | scan, up to 2 | simulated survival table | 500 |
| win-surv | category-win curve | none | simulated survival table | 500 |
| sum1-adp | sum of category z | scan, up to 1 | ADP formula | 250 |
| sum0-adp | sum of category z | never | ADP formula | 250 |
| win-adp-s05 | curve, sigma halved (steeper) | none | ADP formula | 250 |
| win-adp-s2 | curve, sigma doubled (flatter) | none | ADP formula | 250 |

### The category-win curve

- The sum objective maximizes Σ_c T_c, the roster's total z in the active categories. The curve
  maximizes Σ_c Φ((T_c − μ_c) / σ_c): each category counts for the probability that its total
  beats a team drawn from the league, so the objective reads as expected categories won.
- μ_c and σ_c are the mean and standard deviation of the category total over every team in 3000
  simulated all-auto drafts (`sim/curve.json`): means between −0.7 and +0.4 z, spreads 3.5 to
  4.7 z, PTS and STL tightest, TO widest.
- Φ is S-shaped, so the models carry a piecewise-linear version with breakpoints at ±0.5σ,
  ±1.5σ and ±2.5σ and one binary per segment link (`src/pickandroll/optim/objective.py`). Under
  the curve an explicit punt can only remove a non-negative term, so the win conditions run with
  no punt and let the curve concede whatever it cannot win.
- The curve MILP is much harder than the sum at early picks (the LP relaxation can hedge between
  players, which a concave objective rewards): 25 s for the pick-one plan against 0.5 s. The win
  conditions therefore cap the plan at the 80 best availability-weighted candidates per pick
  (objective loss 0.008 of 5.2 at pick one), solve to a 1% MIP gap and stop at 15 s, keeping the
  incumbent.

### Simulated survival

- `scripts/survival_sim.py` ran 3000 drafts in which all twelve teams are simulated drafters
  (same mix as the study's opponents) and recorded where every player went. S[p, k] is the share
  of drafts in which player p was still on the board when overall pick k came up. Simulated
  median pick and ADP correlate at 0.95; the differences are the value drafters' doing (Curry,
  Haliburton, Kyrie and Embiid fall past their ADP, Murray, Mitchell and Towns go earlier).
- The planner uses it conditionally, S[p, k] / S[p, now], exactly as it uses the ADP formula
  1 − Φ((k − adp) / (3 + 0.15·adp)). A player the table has never seen last this long gets no
  credit for lasting longer. This is the greenroom idea from puntgm, now inside the objective
  instead of filtering the candidate list.

## Scores

- value: total z above replacement in the active categories under my best punt (the planner's
  own scale from the earlier study).
- cats won: categories in which my summed z beats an opponent's, averaged over eleven opponents.
- matchups won: opponents beaten in five or more of the nine categories, out of eleven.
- roto: one point per team beaten in each category plus one, out of 108.
- conceded: categories where my total ends at least 4 z below the field's mean.

## Scoreboard (mean ± 95% CI)

| condition | n | value | cats won /9 | matchups won /11 | roto /108 | ranked first | conceded |
|---|---|---|---|---|---|---|---|
| sum-adp | 500 | 71.82 ± 0.35 | 4.63 ± 0.03 | 5.84 ± 0.22 | 59.95 ± 0.35 | 89% | 2.41 |
| sum-surv | 500 | 72.19 ± 0.38 | 4.63 ± 0.03 | 5.76 ± 0.22 | 59.94 ± 0.36 | 90% | 2.47 |
| sum1-adp | 250 | 72.88 ± 0.48 | 4.87 ± 0.04 | 7.43 ± 0.24 | 62.60 ± 0.47 | 92% | 2.09 |
| sum0-adp | 250 | 57.83 ± 0.58 | 5.18 ± 0.05 | 8.10 ± 0.22 | 66.01 ± 0.50 | 13% | 0.54 |
| win-adp | 500 | 66.60 ± 0.50 | 5.50 ± 0.02 | 10.26 ± 0.07 | 69.48 ± 0.25 | 57% | 2.75 |
| win-surv | 500 | 69.53 ± 0.50 | 5.52 ± 0.02 | 10.28 ± 0.07 | 69.72 ± 0.22 | 77% | 2.83 |
| win-adp-s05 | 250 | 64.89 ± 0.66 | 5.54 ± 0.03 | 9.69 ± 0.13 | 69.92 ± 0.35 | 57% | 2.28 |
| win-adp-s2 | 250 | 70.12 ± 0.57 | 5.54 ± 0.03 | 10.04 ± 0.12 | 69.93 ± 0.35 | 82% | 2.23 |

Paired differences against sum-adp, same seeds:

| condition | n | value | cats won | matchups won | roto | matchups better in |
|---|---|---|---|---|---|---|
| sum-surv | 500 | +0.37 ± 0.23 | −0.00 ± 0.03 | −0.08 ± 0.19 | −0.02 ± 0.30 | 35% |
| sum1-adp | 250 | +1.01 ± 0.49 | +0.26 ± 0.06 | +1.68 ± 0.36 | +2.85 ± 0.67 | 67% |
| sum0-adp | 250 | −14.04 ± 0.56 | +0.57 ± 0.06 | +2.35 ± 0.36 | +6.26 ± 0.66 | 74% |
| win-adp | 500 | −5.22 ± 0.50 | +0.87 ± 0.04 | +4.42 ± 0.23 | +9.53 ± 0.41 | 92% |
| win-surv | 500 | −2.29 ± 0.46 | +0.89 ± 0.04 | +4.44 ± 0.23 | +9.77 ± 0.40 | 93% |
| win-adp-s05 | 250 | −6.98 ± 0.82 | +0.92 ± 0.05 | +3.94 ± 0.33 | +10.17 ± 0.58 | 89% |
| win-adp-s2 | 250 | −1.75 ± 0.73 | +0.93 ± 0.05 | +4.29 ± 0.33 | +10.18 ± 0.60 | 92% |

Two-by-two main effects on the four main conditions (objective: curve minus sum; availability:
survival minus ADP; each averaged over the other factor):

| metric | objective | availability | interaction |
|---|---|---|---|
| value | −3.94 ± 0.37 | +1.64 ± 0.31 | +2.56 ± 0.61 |
| cats won | +0.88 ± 0.03 | +0.01 ± 0.02 | +0.02 ± 0.04 |
| matchups won | +4.47 ± 0.20 | −0.03 ± 0.10 | +0.10 ± 0.21 |
| roto | +9.66 ± 0.35 | +0.11 ± 0.20 | +0.25 ± 0.40 |
| share ranked first | −0.23 ± 0.03 | +0.10 ± 0.03 | +0.19 ± 0.05 |

Distribution of matchups won: sum-adp spreads from 1 to 11 with the mode at 6 (16% of drafts)
and 8% at 10 or more; win-surv never finishes below 8 and lands on 10 or 11 in 85% of drafts.

## Where the categories go

Share of opponents beaten, by category:

| condition | PTS | 3PM | REB | AST | STL | BLK | TO | FG% | FT% |
|---|---|---|---|---|---|---|---|---|---|
| sum-adp | 43% | 12% | 96% | 51% | 41% | 80% | 42% | 86% | 11% |
| sum1-adp | 97% | 50% | 88% | 99% | 60% | 20% | 1% | 37% | 36% |
| sum0-adp | 70% | 61% | 60% | 55% | 65% | 57% | 45% | 52% | 53% |
| win-adp | 43% | 6% | 94% | 80% | 94% | 91% | 43% | 94% | 5% |
| win-surv | 60% | 4% | 95% | 86% | 95% | 87% | 29% | 96% | 1% |
| win-adp-s2 | 87% | 24% | 87% | 84% | 87% | 76% | 12% | 79% | 18% |

Mean category totals (z summed over the roster):

| condition | PTS | 3PM | REB | AST | STL | BLK | TO | FG% | FT% |
|---|---|---|---|---|---|---|---|---|---|
| sum-adp | −0.5 | −12.1 | 8.9 | 1.8 | −1.1 | 5.7 | −2.6 | 14.6 | −16.3 |
| win-adp | −3.5 | −11.3 | 6.0 | 3.6 | 4.9 | 5.2 | −1.7 | 8.9 | −15.2 |
| win-surv | −0.5 | −10.6 | 6.3 | 4.5 | 5.1 | 4.7 | −4.2 | 8.9 | −17.0 |
| win-adp-s2 | 3.6 | −5.6 | 5.2 | 4.2 | 3.9 | 2.8 | −6.3 | 6.0 | −11.3 |

Most common conceded sets: sum-adp 3PM + FT% (55%), 3PM + STL + FT% (11%), BLK + TO + FG%
(8%); win-surv 3PM + TO + FT% (54%), PTS + 3PM + FT% (29%), 3PM + FT% (14%); win-adp PTS + 3PM
+ FT% (46%), 3PM + TO + FT% (33%). The one-punt sum planner mostly concedes BLK + TO (26%) or TO
alone (24%), a different build (PTS 97%, AST 99%).

## Availability

Planned players still on the board when their pick came up, all plans pooled:

| condition | planned | expected | realized | Brier | next pick expected | next pick realized |
|---|---|---|---|---|---|---|
| sum-adp | 39000 | 85% | 86% | 0.11 | 89% | 87% |
| sum-surv | 39000 | 88% | 89% | 0.09 | 91% | 92% |
| win-adp | 39000 | 86% | 86% | 0.11 | 90% | 88% |
| win-surv | 39000 | 91% | 92% | 0.07 | 93% | 93% |
| sum0-adp | 19500 | 72% | 46% | 0.28 | 82% | 59% |
| win-adp-s2 | 19500 | 81% | 69% | 0.21 | 87% | 77% |

The ADP formula is calibrated on average for the punting planners, whose targets are niche
players nobody else wants, and badly over-optimistic for the no-punt planner, whose targets are
the consensus names (planned for the next pick with 82% odds, there 59% of the time). The
survival table is calibrated everywhere it was tried and sharper (Brier 0.07 to 0.09).

## Slot and opponents

Matchups won by slot group (1 to 4, 5 to 8, 9 to 12): sum-adp 6.17, 6.29, 5.04; win-adp 10.35,
10.19, 10.24; win-surv 10.43, 10.18, 10.23. By the number of LP opponents (0 to 2, 3 to 4, 5 or
more): sum-adp 6.65, 5.80, 5.31; win-surv 10.38, 10.36, 10.09. The curve's edge is insensitive
to both; the sum planner's category record is where slot and opponents show up.

## Cost

| condition | s per mock | plan solve | picks at the time limit |
|---|---|---|---|
| sum-adp | 94 | 0.16 s | 0 of 13 |
| sum0-adp | 11 | 0.16 s | 0 of 13 |
| win-adp | 122 | 8.8 s | 3.9 of 13 |
| win-surv | 129 | 9.3 s | 4.8 of 13 |
| win-adp-s2 | 90 | 6.4 s | 1.0 of 13 |

Under the curve the plan solve hits the 15 s limit in 95 to 100% of pick-one solves, 70 to 94%
at pick two, about half through pick five, 10% at pick eight and never from pick ten (5 s, 2 s,
0.4 s at pick 13), all measured with ten drafts sharing ten cores. Idle-machine times are
roughly 1.5 to 2 times shorter. The early solves are therefore truncated incumbents, so the
curve's results are a lower bound on what the exact optimum would do. Mitigations that need no
bigger machine: re-solve after every opponent pick (the design's "roll"), so the recommendation
is at most one pick stale when my turn comes; a warm start from the previous plan; a hard 8 s
budget (pick-one loss 0.15 expected wins at 10 s, shrinking later); pricing of alternatives with
the fast sum model or only for the top three names.

## Caveats

- Opponents are simulated: z-score, ADP and LP drafters with a fixed punt mix. The curve's
  build (steals and bigs, concede 3PM and FT%) exploits what these opponents leave on the
  board. Real leagues may value steals or bigs differently; the survival table and the league
  curve both need rebuilding from real draft data before the live draft.
- Win odds use season-total z. Real weeks are noisier, which flattens the true curve; the
  doubled-sigma condition losing almost nothing (10.04 vs 10.26 matchups, and 3.5 z more
  value) is the reason to prefer a flatter curve until weekly variance is modelled.
- Category totals are projections with no injuries or streaming, and both the sum and the
  curve planners see the same opponents, so this is a comparison of objectives, not a forecast
  of a record.
- Early curve solves were truncated at 15 s under full load; the exact optimum could differ
  in either direction, most likely upward for the curve.

## Decisions

Recorded in `docs/ROADMAP.md`: the curve becomes the default objective, with an explicit punt
only as a what-if; per-category odds and marginal value drive a Categories card in the
dashboard; the survival table becomes the default availability when one exists for the
league's drafter mix; sigma is taken at or above the league fit.

## Round leverage

Pending: `data/studies/2026-09-23/leverage/` when the branches finish (win-surv 70 seeds,
sum-adp 50 seeds, thirteen branches each).

## Rerun

```bash
python scripts/survival_sim.py --sims 3000 --out data/studies/2026-09-23/sim --workers 10
bash data/studies/2026-09-23/run_all.sh    # stage 1 (the conditions above)
python scripts/mock_compare.py --out data/studies/2026-09-23 --baseline sum-adp
bash data/studies/2026-09-23/run_all2.sh   # leverage branches, then more seeds
python scripts/mock_leverage.py --out data/studies/2026-09-23 --runs win-surv-naive sum-adp-naive
```
