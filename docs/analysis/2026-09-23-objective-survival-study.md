# Objective and availability study, 2026-09-23

Does the planner win more with a category-win objective (the "S-curve") instead of the sum of
z, and with simulated survival rates instead of the ADP formula? Run of 2026-09-22 to 23: 3000
all-auto drafts for the survival table and league curve, then eight planner settings through
the same simulated leagues, 1000 seeds for the four main conditions and 500 for the rest.
Per-mock data, CSV tables and `compare/report.html` are in `data/studies/2026-09-23/` (not
committed, built on subscriber projections). The round-leverage experiment (which rounds the
planner's pick is worth most) ran afterwards; its section is at the end.

## Findings

- **The S-curve wins matchups; the sum of z wins its own scoreboard.** Same leagues, same
  opponents: sum-of-z with a two-category punt wins 5.88 of 11 head-to-head matchups, the curve
  10.27 (ADP odds) or 10.29 (survival odds). Categories won per matchup 4.64 vs 5.49 to 5.52;
  roto points 60.1 vs 69.4 to 69.7. Paired by seed the curve is +4.4 matchups (95% CI ±0.16) and
  better in 92 to 93% of seeds. It finishes with 10 or 11 matchups won in 84 to 86% of drafts;
  the sum planner does in 8%.
- **Value and category wins pull apart.** The curve gives up 5.1 z of value against the sum
  planner under ADP odds, 2.4 z under survival odds, and is ranked first by value in 58 to 75%
  of leagues instead of 88%. Value is the sum planner's own objective; nothing else tracks it.
- **A punt is an outcome, not a goal.** The curve gets no punt and still concedes 2.8 categories
  on average (three in 79 to 81% of drafts): 3PM and FT% almost always, TO or PTS as the third.
  The sum planner's explicit two-punt scan concedes 2.4. The difference is where the surplus
  goes: the sum planner ends with FG% +14.8 z and REB +8.9 z (won 87% and 96% of the time) and
  coin flips on PTS, AST, STL and TO (41 to 51%); the curve ends with STL +5.0, AST +3.7 to
  +4.5, BLK +4.7 to +5.2, FG% +8.8 and wins AST 81 to 86%, STL 94%, BLK 88 to 90%, FG% 94 to 96%.
- **Punt width matters under the sum objective too.** One punt instead of two: +1.5 matchups
  (±0.26). No punt at all: +2.3 matchups while losing 13.9 z of value. Explicit punts were free
  only on the z scale.
- **Survival rates change nothing under the sum objective** (−0.12 matchups, ±0.13; value
  +0.28 ±0.16). Under the curve they recover value without touching wins: interaction +2.5 z
  (±0.4), share ranked first from 58% to 75%. The table is better calibrated than the formula
  (planned players available 92% realized vs 91% expected, Brier 0.07 against 0.11) and the
  gain lands on the specific later-round targets the curve leans on.
- **The curve's odds are conservative.** Expected categories won at pick one 5.00 to 5.03;
  realized 5.49 to 5.52. Re-planning against the real board adds about half a category, the
  same pattern the earlier study found for the value benchmark.
- **Sigma.** Halving sigma (steeper, all-or-nothing) loses: 9.63 matchups, value 65.1. Doubling
  it (flatter, closer to the plain sum) costs little: 10.08 matchups, value 70.3, rank-first
  84%, and it concedes less extreme totals. Real weeks are noisier than season totals, which
  argues for the flatter curve; take sigma at or above the league fit, not below.
- **Slot and opponents stop mattering.** The sum planner falls from 6.1 matchups in slots 1 to
  4 to 5.1 in slots 9 to 12 and from 6.4 with two or fewer LP opponents to 5.5 with five or more.
  The curve sits at 10.1 to 10.5 across slots and 10.1 to 10.4 across opponent mixes.
- **The curve drafts differently from pick one.** In the first 500 seeds, from slot 3 onward it
  took Dyson Daniels first in 56 to 95% of drafts under ADP odds (36 to 73% under survival
  odds), ahead of Luka, Shai and Tatum, because elite steals are scarce and the bigs that win
  REB, BLK and FG% keep falling in these simulated drafts. Under survival odds it takes Jokic
  over Wembanyama at slot 1 (95%). Both are the optimizer reading the simulated opponents, and
  both are exactly the kind of choice to test against real draft data before trusting. The
  round-leverage experiment below shows the pick-one choice does not matter either way.
- **Cost.** Sum objective: 0.16 s per plan, 94 s per mock (the punt scan dominates). Curve: 8.8
  to 9.6 s per plan on a loaded core with the 80-candidate cap, hitting the 15 s limit in 3.9
  to 5.0 of 13 picks (picks one to five mostly), 122 to 133 s per mock. See "Cost" below.

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
| sum-adp | sum of category z (the planner as studied on 2026-09-22) | scan, up to 2 | ADP formula | 1000 |
| win-adp | category-win curve | none (the curve concedes on its own) | ADP formula | 1000 |
| sum-surv | sum of category z | scan, up to 2 | simulated survival table | 1000 |
| win-surv | category-win curve | none | simulated survival table | 1000 |
| sum1-adp | sum of category z | scan, up to 1 | ADP formula | 500 |
| sum0-adp | sum of category z | never | ADP formula | 500 |
| win-adp-s05 | curve, sigma halved (steeper) | none | ADP formula | 500 |
| win-adp-s2 | curve, sigma doubled (flatter) | none | ADP formula | 500 |

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
| sum-adp | 1000 | 71.83 ± 0.25 | 4.64 ± 0.02 | 5.88 ± 0.16 | 60.05 ± 0.25 | 88% | 2.44 |
| sum-surv | 1000 | 72.11 ± 0.26 | 4.63 ± 0.02 | 5.76 ± 0.15 | 59.97 ± 0.25 | 88% | 2.48 |
| sum1-adp | 500 | 72.68 ± 0.35 | 4.86 ± 0.03 | 7.34 ± 0.17 | 62.45 ± 0.33 | 92% | 2.07 |
| sum0-adp | 500 | 57.90 ± 0.43 | 5.21 ± 0.03 | 8.18 ± 0.15 | 66.27 ± 0.37 | 15% | 0.55 |
| win-adp | 1000 | 66.72 ± 0.36 | 5.49 ± 0.02 | 10.27 ± 0.05 | 69.42 ± 0.18 | 58% | 2.75 |
| win-surv | 1000 | 69.48 ± 0.35 | 5.52 ± 0.01 | 10.29 ± 0.05 | 69.73 ± 0.16 | 75% | 2.80 |
| win-adp-s05 | 500 | 65.11 ± 0.46 | 5.54 ± 0.03 | 9.63 ± 0.09 | 69.95 ± 0.28 | 59% | 2.25 |
| win-adp-s2 | 500 | 70.34 ± 0.39 | 5.56 ± 0.02 | 10.08 ± 0.09 | 70.14 ± 0.26 | 84% | 2.23 |

Paired differences against sum-adp, same seeds:

| condition | n | value | cats won | matchups won | roto | matchups better in |
|---|---|---|---|---|---|---|
| sum-surv | 1000 | +0.28 ± 0.16 | −0.01 ± 0.02 | −0.12 ± 0.13 | −0.08 ± 0.21 | 35% |
| sum1-adp | 500 | +0.86 ± 0.36 | +0.23 ± 0.04 | +1.50 ± 0.26 | +2.50 ± 0.46 | 64% |
| sum0-adp | 500 | −13.93 ± 0.39 | +0.57 ± 0.04 | +2.34 ± 0.25 | +6.32 ± 0.47 | 74% |
| win-adp | 1000 | −5.11 ± 0.35 | +0.85 ± 0.03 | +4.39 ± 0.16 | +9.36 ± 0.29 | 92% |
| win-surv | 1000 | −2.35 ± 0.33 | +0.88 ± 0.03 | +4.41 ± 0.16 | +9.68 ± 0.28 | 93% |
| win-adp-s05 | 500 | −6.71 ± 0.57 | +0.91 ± 0.04 | +3.79 ± 0.23 | +10.00 ± 0.42 | 88% |
| win-adp-s2 | 500 | −1.48 ± 0.50 | +0.93 ± 0.04 | +4.24 ± 0.23 | +10.18 ± 0.41 | 92% |

Two-by-two main effects on the four main conditions (objective: curve minus sum; availability:
survival minus ADP; each averaged over the other factor):

| metric | objective | availability | interaction |
|---|---|---|---|
| value | −3.87 ± 0.26 | +1.52 ± 0.22 | +2.48 ± 0.43 |
| cats won | +0.87 ± 0.02 | +0.01 ± 0.01 | +0.04 ± 0.03 |
| matchups won | +4.46 ± 0.14 | −0.05 ± 0.07 | +0.14 ± 0.15 |
| roto | +9.56 ± 0.25 | +0.12 ± 0.14 | +0.40 ± 0.28 |
| share ranked first | −0.22 ± 0.02 | +0.09 ± 0.02 | +0.17 ± 0.04 |

Distribution of matchups won: sum-adp spreads from 1 to 11 with the mode at 6 (14% of drafts)
and 8% at 10 or more; win-surv never finishes below 8 and lands on 10 or 11 in 85% of drafts.

## Where the categories go

Share of opponents beaten, by category:

| condition | PTS | 3PM | REB | AST | STL | BLK | TO | FG% | FT% |
|---|---|---|---|---|---|---|---|---|---|
| sum-adp | 42% | 12% | 96% | 51% | 41% | 81% | 43% | 87% | 10% |
| sum1-adp | 97% | 51% | 87% | 99% | 59% | 21% | 1% | 35% | 37% |
| sum0-adp | 69% | 61% | 61% | 55% | 65% | 60% | 44% | 53% | 54% |
| win-adp | 43% | 6% | 94% | 81% | 94% | 90% | 42% | 94% | 4% |
| win-surv | 61% | 4% | 95% | 86% | 94% | 88% | 28% | 96% | 1% |
| win-adp-s2 | 87% | 24% | 88% | 85% | 88% | 76% | 11% | 80% | 18% |

Mean category totals (z summed over the roster):

| condition | PTS | 3PM | REB | AST | STL | BLK | TO | FG% | FT% |
|---|---|---|---|---|---|---|---|---|---|
| sum-adp | −0.6 | −12.3 | 8.9 | 1.6 | −1.1 | 5.8 | −2.5 | 14.8 | −16.5 |
| win-adp | −3.4 | −11.4 | 6.0 | 3.7 | 5.0 | 5.2 | −1.8 | 8.9 | −15.3 |
| win-surv | −0.4 | −10.5 | 6.2 | 4.5 | 5.1 | 4.7 | −4.2 | 8.8 | −16.8 |
| win-adp-s2 | 3.6 | −5.7 | 5.2 | 4.3 | 4.0 | 2.9 | −6.4 | 6.0 | −11.4 |

Most common conceded sets: sum-adp 3PM + FT% (53%), 3PM + STL + FT% (10%), BLK + TO + FG%
(8%); win-surv 3PM + TO + FT% (52%), PTS + 3PM + FT% (28%), 3PM + FT% (15%); win-adp PTS + 3PM
+ FT% (46%), 3PM + TO + FT% (33%). The one-punt sum planner mostly concedes BLK + TO (26%) or TO
alone (25%), a different build (PTS 97%, AST 99%).

## Availability

Planned players still on the board when their pick came up, all plans pooled:

| condition | planned | expected | realized | Brier | next pick expected | next pick realized |
|---|---|---|---|---|---|---|
| sum-adp | 78000 | 85% | 86% | 0.11 | 89% | 87% |
| sum-surv | 78000 | 88% | 89% | 0.09 | 92% | 92% |
| win-adp | 78000 | 86% | 86% | 0.11 | 90% | 87% |
| win-surv | 78000 | 91% | 92% | 0.07 | 93% | 93% |
| sum0-adp | 39000 | 72% | 47% | 0.28 | 82% | 59% |
| win-adp-s2 | 39000 | 81% | 69% | 0.21 | 87% | 77% |

The ADP formula is calibrated on average for the punting planners, whose targets are niche
players nobody else wants, and badly over-optimistic for the no-punt planner, whose targets are
the consensus names (planned for the next pick with 82% odds, there 59% of the time). The
survival table is calibrated everywhere it was tried and sharper (Brier 0.07 to 0.09).

## Slot and opponents

Matchups won by slot group (1 to 4, 5 to 8, 9 to 12): sum-adp 6.13, 6.36, 5.14; win-adp 10.40,
10.16, 10.23; win-surv 10.51, 10.14, 10.22. By the number of LP opponents (0 to 2, 3 to 4, 5 or
more): sum-adp 6.42, 5.85, 5.52; win-surv 10.44, 10.33, 10.12. The curve's edge is insensitive
to both; the sum planner's category record is where slot and opponents show up.

## Cost

| condition | s per mock | plan solve | picks at the time limit |
|---|---|---|---|
| sum-adp | 94 | 0.16 s | 0 of 13 |
| sum0-adp | 12 | 0.16 s | 0 of 13 |
| win-adp | 122 | 8.8 s | 3.9 of 13 |
| win-surv | 133 | 9.6 s | 5.0 of 13 |
| win-adp-s2 | 95 | 6.7 s | 1.2 of 13 |

Under the curve the plan solve hits the 15 s limit in 95 to 100% of pick-one solves, 70 to 94%
at pick two, about half through pick five, 10% at pick eight and never from pick ten (5 s, 2 s,
0.4 s at pick 13), all measured with ten drafts sharing ten cores. Idle-machine times are
roughly 1.5 to 2 times shorter. The early solves are therefore truncated incumbents, so the
curve's results are a lower bound on what the exact optimum would do. Mitigations that need no
bigger machine: re-solve after every opponent pick (the design's "roll"), so the recommendation
is at most one pick stale when my turn comes; a warm start from the previous plan; a hard 8 s
budget (pick-one loss 0.15 expected wins at 10 s, shrinking later); pricing of alternatives with
the fast sum model or only for the top three names. The round-leverage result below adds the
simplest one: the pick-one solve can be skipped altogether.

## Caveats

- Opponents are simulated: z-score, ADP and LP drafters with a fixed punt mix. The curve's
  build (steals and bigs, concede 3PM and FT%) exploits what these opponents leave on the
  board. Real leagues may value steals or bigs differently; the survival table and the league
  curve both need rebuilding from real draft data before the live draft.
- Win odds use season-total z. Real weeks are noisier, which flattens the true curve; the
  doubled-sigma condition losing almost nothing (10.08 vs 10.27 matchups, and 3.6 z more
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

Which rounds does the planner's pick matter in? For each finished draft and each of my picks
k, the draft was replayed to pick k, the consensus player (best available by ADP order, here
BBM's rank) was taken instead of the planner's choice, and the planner drafted the rest. The
paired loss, original minus branch, is the incremental alpha of the planner's pick at round k.
Rounds where the consensus and the planner agreed count as zero. Curve planner (win-surv) on
68 seeds, sum planner (sum-adp) on 45; tables and charts in
`data/studies/2026-09-23/leverage/`.

Alpha per round, matchups won of 11, mean ± 95% CI (value alpha in z after it):

| round | win-surv: matchups | value | same pick | sum-adp: matchups | value | same pick |
|---|---|---|---|---|---|---|
| 1 | −0.04 ± 0.22 | +0.1 | 26% | −0.18 ± 0.56 | +0.9 | 69% |
| 2 | +0.25 ± 0.21 | +2.3 | 9% | +0.69 ± 0.81 | +2.9 | 7% |
| 3 | +0.22 ± 0.25 | +4.2 | 0% | +0.44 ± 0.73 | +3.2 | 4% |
| 4 | +0.06 ± 0.23 | +1.8 | 1% | −0.51 ± 0.76 | +2.2 | 0% |
| 5 | +0.18 ± 0.27 | +1.9 | 6% | +0.20 ± 0.85 | +2.1 | 4% |
| 6 | +0.07 ± 0.23 | +1.1 | 12% | +0.04 ± 0.55 | +1.7 | 11% |
| 7 | +0.34 ± 0.20 | +2.2 | 4% | −0.18 ± 0.54 | +2.5 | 2% |
| 8 | +0.18 ± 0.23 | +2.0 | 3% | −0.16 ± 0.45 | +2.2 | 2% |
| 9 | +0.28 ± 0.29 | +2.7 | 3% | −0.02 ± 0.43 | +2.5 | 0% |
| 10 | +0.25 ± 0.21 | +2.8 | 3% | −0.07 ± 0.61 | +3.0 | 2% |
| 11 | +0.12 ± 0.19 | +2.3 | 4% | +0.27 ± 0.48 | +2.9 | 7% |
| 12 | +0.29 ± 0.21 | +2.5 | 0% | +0.42 ± 0.42 | +3.5 | 0% |
| 13 | +0.43 ± 0.22 | +2.2 | 0% | +0.09 ± 0.51 | +3.7 | 0% |

- **Round one is a commodity pick under the curve.** The planner disagrees with the consensus
  there in 74% of drafts (Daniels, Jokic) and it makes no difference: −0.04 matchups, +0.1 z.
  Whichever star opens the draft, the plan recovers. The 15 s pick-one solve buys nothing; a
  consensus top pick and the budget spent from round two would do.
- **Every later round carries alpha, the late ones most.** Rounds 2 to 13 are each worth 0.06
  to 0.43 matchups, about 2.7 over the draft, with rounds 7, 9, 10, 12 and 13 at the top
  (0.25 to 0.43) and round 13 the single largest. Late in the draft the consensus pick is a
  generic scorer and the curve wants a category filler (a big, a steals guard), and that
  gap is what the alpha measures. The per-round alphas add to less than the 4.4-matchup gap
  between the curve and the sum planner because one consensus pick is largely repaired by
  the picks after it.
- **The sum planner has no matchup leverage anywhere.** Its pick beats the consensus by 0.9
  to 3.7 z of value in every round and by nothing in matchups (every CI covers zero, round
  four −0.51). Value earned round by round does not turn into category wins; the objective,
  not the round, is the problem.
- **What this changes** (`docs/ROADMAP.md`): compute and attention go to rounds two onward,
  late rounds included, not to pick one; the dashboard should show the cost of a deviation on
  the matchup scale, which is roughly a quarter of a matchup per round under the curve; and
  the late-round alternatives deserve the same solver budget as the early ones, which they get
  anyway because the curve solves fast from pick eight on.

## Rerun

```bash
python scripts/survival_sim.py --sims 3000 --out data/studies/2026-09-23/sim --workers 10
bash data/studies/2026-09-23/run_all.sh    # stage 1 (the conditions above at 500 / 250 seeds)
bash data/studies/2026-09-23/run_all2.sh   # leverage branches, then stage 2 (1000 / 500 seeds)
python scripts/mock_compare.py --out data/studies/2026-09-23 --baseline sum-adp
python scripts/mock_leverage.py --out data/studies/2026-09-23 --runs win-surv-naive sum-adp-naive
```
