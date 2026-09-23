# Prospective changes

Decisions taken on 2026-09-23 from the objective and availability study
(`docs/analysis/2026-09-23-objective-survival-study.md`, in progress). Not yet built.

## Principle: a punt is an outcome, not a goal

The category-win curve (`optim/objective.py`) values each category by its odds of beating the
field, so the planner concedes a category only when the board has made it unwinnable, and can
take it back if a cheap fix falls. The sum-of-z objective with an explicit two-category punt
maximized its own scale but won barely half of its head-to-head matchups in simulation; the
curve won over ninety percent. The product should follow the curve: nothing in the main path
asks the user to choose a punt, and nothing labels a pick with one.

## Solver and API

1. `objective: sum | win` on the recommend, plan and score endpoints, default `win`. The curve's
   mean and spread per category default to the simulated league (`survival_sim.py` output) and
   can be overridden from a file for a specific league.
2. Expose per category: expected final total from the plan, win odds under the curve, and the
   marginal value (slope of the curve at the expected total). The slope is what tells the user
   where the next pick should invest.
3. `punt` stays as an optional constraint for what-if solves ("what if I commit to conceding X")
   and is never chosen automatically on the default path. The roster punt scan becomes a
   what-if tool, not the first step of a recommendation.
4. Survival-table availability as the default when a table for the league's drafter mix exists;
   the ADP formula stays as the fallback and for players the table lacks.
5. Session scoreboard: expected and realized categories won and matchups alongside value.

## Dashboard

1. New Categories card as the centrepiece: one row per category with my drafted total, the
   plan's expected final total, win odds, teams beaten right now, and the marginal value. Shade
   rows conceded (odds near zero), contested, and secured.
2. Punt card demoted to the strategy drawer as a what-if; no punt badge on the recommended pick.
3. Team card: expected categories won next to value; benchmark on the same scale.
4. Opponent view: each opponent's category totals so far, to see who competes where.

## Checks before drafting on it

- Compare the curve's expected wins at pick one with realized wins in the study, so the odds
  shown on the card are known to be honest.
- Sigma sensitivity (`win-adp-s05`, `win-adp-s2` conditions): real weeks are noisier than
  season totals, which argues for a flatter curve; pick sigma from that result.
- Rebuild the survival table from opponents that resemble the real league once its drafters
  are known.

## Ideas, not yet decided (2026-09-23)

The planner treats the opponents as a fixed population and the league as a static prior.
Candidates for closing that gap, cheapest first:

1. **Matchup-aware curve.** Score a category by the number of the eleven actual opponents I
   beat, projecting each opponent's final total from their drafted players plus
   replacement-level fill. Marginal value then goes where the most opponents can be flipped
   and a category the whole league concedes becomes cheap. Pure bookkeeping on the pick log.
2. **Oracle experiment.** Give the planner the true opponent drafter types and punts in the
   harness and measure the gain; it bounds what any detection can be worth.
3. **Type-conditional survival.** Detect each opponent's drafter type from their picks (the
   2026-09-22 study's classifier) and mix per-type survival tables by the posterior, aimed at
   the players LP teams snipe.
4. **Intervening-team conditioning.** For the pick right before mine, condition availability
   on what the teams picking in between still need.
5. **Equilibrium study.** Run the harness with opponents that also draft on the curve and see
   whether the edge shrinks and which categories crowd.

Data that would calibrate availability from history instead of simulation:

- Real ADP once preseason mocks run (Yahoo, ESPN, FantasyPros, Hashtag Basketball, BBM's ADP
  column, empty in the September export).
- Any archive of real draft results (Yahoo mock logs, past league drafts) to fit the spread of
  pick minus ADP by ADP band, replacing the guessed 3 + 0.15·adp.
- The league's own past drafts per manager: who reaches, who follows ADP, who punts what.
  Opponent priors before pick one instead of inference from round three.

## Round leverage (2026-09-23)

The harness measures the planner's incremental alpha per round: replay a finished draft to my
pick k, make the consensus pick there (best available by ADP order), let the planner finish, and
score the paired loss (`scripts/mock_study.py --naive-branches`, `scripts/mock_leverage.py`).
Rounds where the consensus and the planner agree are zero alpha by construction. Once the
profile is known:

- **Compute goes where alpha is.** Rounds with near-zero alpha (the planner takes the
  consensus anyway) do not need the slow curve solve; take the board. Spend the budget on the
  rounds that matter: longer time limit, tighter gap, priced alternatives. This is also the
  answer to pick-time worries: the curve solve takes 8 to 15 s at picks one to five and under
  3 s from pick eight, and the plan re-solves after every opponent pick, so by my turn the
  recommendation is at most one pick stale.
- **Attention goes where alpha is.** The dashboard should show the cost of deviating from the
  plan in the current round on the matchup scale, so a gut pick is known to be cheap or dear.
- **Preparation goes where alpha is.** High-alpha rounds are where projections and availability
  odds matter most: injury news, eligibility and target lists for those rounds; opponent
  modelling and survival tables pay there.
- **Truncated solves.** If alpha concentrates in rounds where the curve solve hits its time
  limit, the measured alpha is a lower bound and the solver deserves a warm start or a larger
  budget there.
- **Not a weight.** The objective already values every pick by its marginal effect; per-round
  alpha is a diagnostic. A "focus" multiplier on high-leverage rounds would double count. The
  strategic reading is the only model-level consequence: if the draft is won in the middle
  rounds, the early picks are commodity and the middle picks decide the roster's category
  shape.
