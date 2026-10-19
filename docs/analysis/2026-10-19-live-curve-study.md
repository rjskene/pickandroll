# Live curve study (2026-10-19)

**Question.** The win objective scores each category against a curve, the league's mean and spread of
final category totals, fixed at the attach from the archive's rosters. Can the curve be computed from
the draft in progress instead, and is it better calibrated?

**Data.** The four categories drafts of 2026-10-18 and 2026-10-19 (252098, 31153, 224319, 258332): 12
teams, 13 rounds, each session's own z (pool 156) and ADP from its fidelity folder. Team totals
recomputed from the pick logs match the sessions' own totals to 0.003 z. Scripts and per-case outputs
are in the scratch repo (`master/live-curve-2026-10-19/`), outside this repository.

**Method.** At every twelfth pick, each team's projected final per category is its drafted z plus a fill
for each of its remaining pick numbers, with a variance per fill. Three fills:

- **A, ADP kernel.** The mean z of the still-available players weighted by a Gaussian in ADP around the
  pick number, spread `1.5 + 0.15 n` (the survival model's), at least ten players.
- **B1, slot value.** The mean z of the player actually taken at pick `n` in the *other three* drafts,
  smoothed over `n` (sd 4 picks); the variance from the smoothed residuals. Leave-one-out throughout.
- **B2.** A plus the other drafts' mean gap between the player taken at `n` and the kernel's fill.

Odds in a category are the mean over the eleven opponents of Φ((my final − their projected final) /
their fill sd), with my final taken as known, and are scored by Brier against the fraction of opponents
my final actually beats. The **prior** is the leave-one-out curve from the other three drafts' finals,
the equivalent of today's `curve: league`.

## Findings

1. **The ADP-neighbourhood fill runs low.** About 0.06 z per slot per category before pick 60 and 0.13
   after pick 90: late picks are the best available player, not a player near the pick's ADP. Opponents
   then look weaker than they end up and the live odds average 0.57 where the truth is 0.50. The flat
   replacement fill the dashboard's league table shows today is far lower still: 4.4 z per team and
   category at pick 0, 1.9 at pick 48, and honest only after pick 120.
2. **The slot-value fill is unbiased and calibrated.** Its bias is within 0.03 z at every pick, and the
   independent-slot variance needs no inflation (a factor of 1 scores best; 1.5 and 2 score worse).
3. **Per-opponent odds on the slot-value fill beat the fixed curve at every pick** and never lose:

   | pick | prior | live mixture |
   |---|---|---|
   | 0 | 0.0091 | 0.0081 |
   | 36 | 0.0091 | 0.0078 |
   | 72 | 0.0091 | 0.0069 |
   | 96 | 0.0091 | 0.0060 |
   | 120 | 0.0091 | 0.0046 |
   | 144 | 0.0091 | 0.0030 |

   Brier, lower is better. Before pick 48 the per-category differences are within the noise of four
   drafts (live is worse in field-goal percentage and rebounds, better in free throws and turnovers);
   from pick 96 on live is better in all nine.
4. **One re-fitted normal is not enough.** Moment-matching the eleven opponents to a single mean and
   spread tracks the mixture to pick 60 and then stalls at 0.006. Its width never narrows: the spread
   between opponents' projected finals grows exactly as their fill variance shrinks (0.4 and 3.2 at pick
   0, 3.3 and 0 at the end, sum near 3.2 throughout). The curve does not get narrower as the draft goes;
   it resolves into eleven points. The implementation has to score per opponent.
5. **The early curve is not over-steep.** The slot-value spread at pick 0 (3.16 z) is within five
   percent of the prior's (3.33), and the realized error is 1.08 times the predicted. Widening the curve
   for estimation error would be a ten-percent change at most. The early specialist reaches of
   2026-10-18 came from the simulated survival table, since replaced by the archive's; this study finds
   no second early-round cause.

## Recommendation

Build the matchup-aware objective (`docs/ROADMAP.md`, ideas, item 1) with slot-value fills:

- An opponent's projected final per category is their drafted z plus the archive's slot value for each
  of their remaining pick numbers, with the slot variance summed; fitted from every archived draft of the
  format (the other format at half weight) in the same refit that builds the survival table at `run`.
- Win odds per category are the mean over opponents of Φ on those finals, and the marginal value is the
  mean of the eleven slopes. My own total stays the plan's expectation.
- The dashboard's league table and head-to-head tally use the same fills, which removes today's flat
  fill bias from what the user watches.
- Solver: the objective's piecewise-linear curve per category becomes a per-category mixture of eleven
  normals, whose breaks must follow the opponents' finals rather than fixed multiples of one sigma. The
  shape is still monotone but has eleven inflection points; how the current linearisation copes is the
  first thing to check.

The gain is calibration from the middle rounds on, where the leverage study put the alpha, not in the
early rounds. It changes the objective and the API, so it waits for a day without drafts.
