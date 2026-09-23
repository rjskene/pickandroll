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
