# Roadmap

## Built (2026-09-24)

The decisions of 2026-09-23 (`docs/analysis/2026-09-23-objective-survival-study.md`) are in the
product. Formulations in `docs/DESIGN.md`.

- **Objective `win` by default.** Sessions plan on the category-win curve; `objective: sum` is
  the old planner without a punt. Nothing in the API or UI chooses or pins a punt; the solver's
  punt arguments remain for the study harness only. The curve's mean and spread come from the
  simulated league of the study (`CategoryCurve.simulated`), a JSON file (`curve_file`) or the
  session's own league simulation, with `sigma_scale` as the weekly-noise hedge.
- **Survival table at setup.** `survival: simulate` runs an all-auto league simulation in the
  background (`draft/league_sim.py`, 300 drafts by default, progress over the event stream) and
  refits the curve from the same run; `survival: file` loads a saved table; the ADP formula is
  the fallback and covers players a table lacks.
- **Per-category report.** Every recommendation carries, per category, my drafted total, the
  expected final, win odds, a conceded/contested/secured label, the marginal value (the curve's
  slope), and the opponents beaten now and at the end; plus the head-to-head tally against every
  opponent's projected final.
- **Solve ahead of the clock.** A background solver per session re-plans after every change,
  prices alternatives to first order at once and exactly in the process pool, solves "if he is
  gone" scenarios while someone else picks, and publishes a `recommendation` event. Time limits
  keep the incumbent; a curve solve with no incumbent falls back to the sum plan and says so.
- **Scoreboard on the win scale.** Expected categories won before my first pick, the best plan
  seen during the draft, the latest, and the final roster's odds and matchups.
- **Dashboard.** A Categories card (odds, labels, marginal value, league table with every team's
  drafted and projected totals), the punt card and badges gone, deviation cost per alternative
  and per board row, the Team card on the win scale, the setup form's strategy and availability
  options, a stale marker while a re-plan is under way.
- **First manual test (2026-09-26).** Ties: candidates within 0.05 categories of the best are
  shown as a group with ADP as the consensus order, since the model cannot separate them (at
  pick 5 on an empty roster it priced Luka Doncic 0.03 behind Dyson Daniels, the scarce piece
  of a three-category concession build). Board costs are the exact re-solve where one exists,
  estimates marked. Cards show placeholders while a re-plan runs, so a drafted name never
  sits in the recommended slot. "Survival odds" everywhere, the concession strip on the Pick
  card, the plan as one table, info popovers on the setup form, a resizable drawer, and a loud
  warning when no ADP file is loaded (a value rank places specialists far too late, which
  flatters concession builds). Late-season durability is issue #2.

## Checks before drafting on it

- Rebuild the survival table from opponents that resemble the real league once its drafters
  are known (the setup form's drafter mix), and compare the curve's expected wins at pick one
  with realized wins in a mock on the real board.
- Real ADP once preseason mocks run, and the solve-ahead loop against the Yahoo feed once the
  API is approved (issue #1).

## Ideas, not yet decided (2026-09-23)

The planner treats the opponents as a fixed population and the league as a static prior.
Candidates for closing that gap, cheapest first:

1. **Matchup-aware curve.** Score a category by the number of the eleven actual opponents I
   beat, projecting each opponent's final total from their drafted players plus
   replacement-level fill. The tally is now computed live (`DraftState.matchups`); the step
   left is to put it in the objective so marginal value goes where the most opponents can be
   flipped.
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
Rounds where the consensus and the planner agree are zero alpha by construction. Result
(2026-09-23, curve planner, 68 seeds): round one is worth nothing (−0.04 matchups even though
the planner's pick differs from the consensus 74% of the time), rounds two to thirteen are
each worth 0.06 to 0.43 matchups with the late rounds highest, and the sum-of-z planner has
no matchup leverage in any round. Consequences:

- **Compute runs ahead of the clock, not against it.** Built: see above. Pick one has no alpha
  anyway, so whatever it names is fine.
- **Attention goes where alpha is.** Built: the cost of deviating from the plan is on every
  alternative and every board row, on the matchup scale.
- **Preparation goes where alpha is.** High-alpha rounds are where projections and availability
  odds matter most: injury news, eligibility and target lists for those rounds; opponent
  modelling and survival tables pay there.
- **Truncated solves.** If alpha concentrates in rounds where the curve solve hits its time
  limit, the measured alpha is a lower bound and the solver deserves a warm start or a larger
  budget there. The solver now reports when a plan or a price was time-limited.
- **Not a weight.** The objective already values every pick by its marginal effect; per-round
  alpha is a diagnostic. A "focus" multiplier on high-leverage rounds would double count.

## Draft-day news (2026-09-23)

Basketball Monster already folds injury news into its rest-of-season projections and updates
several times a day, so real-time coverage during a draft is about refreshing and flagging,
not re-deriving rankings from headlines.

1. **Mid-draft projection refresh.** A "refresh projections" action on the session runs the BBM
   fetcher (`scripts/bbm_fetch.py`, headed login), recomputes z and re-solves without touching
   the pick log.
2. **News alerts.** Poll an injury feed (Rotowire or Rotoworld headlines, the ESPN injuries
   page) during the draft and flag any player on the board or in the plan whose news is newer
   than the projection file. Alerts only; a headline is not a projection.
3. **Games-played override.** Projections are per game times games, so the honest on-the-fly
   adjustment is a per-player games haircut from the UI ("out four weeks" means about fifteen
   fewer games); z and the plan update at once. This is the manual counterpart to the alert.
4. **Eligibility check.** Flag players whose Yahoo position eligibility differs from the BBM
   export's coarse G/F/C, since slot feasibility depends on it.

### Automated BBM downloads

`scripts/bbm_fetch.py` already drives Basketball Monster through a persistent Playwright
profile: one headed run where the user logs in, then `--headless` reuses the session. Nothing
in the project handles credentials. To make it automatic:

1. The first headed run (pending since 2026-09-21) to create the profile.
2. A macOS launchd agent running `bbm_fetch.py --ros --headless` every few hours in preseason
   and every thirty minutes on draft day, saving timestamped exports into `data/`.
3. The API reloads projections when a newer export appears, or on a "refresh now" action from
   the dashboard, keeping the pick log.
4. When BBM logs the profile out, the job stops and tells the user to redo the headed login. It
   never authenticates on its own.
5. A change summary per new file: players whose games or z moved most since the previous
   export, so the news arrives as a short list.
