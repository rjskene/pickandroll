# The category curve from the league's drafted rosters (#65, 2026-10-16)

Why: the curve a session scores on is simulated. Its per-category spread is 3.5 to 4.7 z; the
twelve rosters drafted on 2026-10-14 spread 2.1 to 3.7 z. A narrower spread sharpens which
categories count as secured or conceded and can change the first-round choice. This note puts
the two curves side by side on that draft. It is a comparison, not a default switch: the fit is
twelve rosters of one season.

## Method

* `curve: league` (`POST /sessions`) fits mu and sigma per category from the league's drafted
  rosters: every archived season with a draft and a projection file, each roster's total the
  sum of its players' z on its season's projections (`CategoryCurve.from_rosters`,
  `api/league_curve.py`). The rosters are the archive's `picks.csv` grouped by the team that made
  each pick, so traded picks and keepers land on the roster that used them. The session's own
  projections score their own season; an earlier season joins when its preseason projections
  are in the archive as `projections_<year>.csv`. Today only 2026 qualifies: 2017-2025 have no
  projection file, and 2015 (ten teams) and 2016 (twelve rounds) are not on a 12 x 13 scale.
* The check: the standings' team spread per category (`category_totals.csv`, per-game
  normalised) over the per-player spread of the session's z pool, which puts the standings in
  z units. It is the 2026-10-06 archive study's conversion, averaged over the ten 12-team
  seasons 2016-17 to 2025-26. It reads the managed roster's season (waivers, injuries,
  streaming), so it should run wider than the drafted rosters. The percentages have no
  conversion without the attempts.
* The comparison: `scripts/league_curve.py` rebuilds the draft night's session twice through
  the API, once per curve, with everything else the same:
  * the room log's last attach (projections of 2026-10-14, positions, ADP, keepers by the picks
    they took);
  * the night's pick owners from `picks.csv` (ten traded picks);
  * the product's default availability for the league: its survival table
    (`survival_by_adp_adjusted.csv`) and the ADP bias (`adp_bias.json`, #64).

  It reports the user's final roster on both curves and the plan at the user's first pick,
  overall 4, after picks 1 to 3. The plan budget was 20 s; both plans converged inside it and
  were priced exactly. Two runs gave identical output.

## 1. The two curves

| cat | mu simulated | mu league | sigma simulated | sigma league | sigma standings (2016-17 to 2025-26) |
|---|---|---|---|---|---|
| pts | -0.41 | 0.23 | 3.54 | 3.23 | 3.58 |
| threes | -0.69 | -0.59 | 4.17 | 2.51 | 3.08 |
| reb | -0.28 | -0.67 | 3.99 | 2.20 | 2.65 |
| ast | 0.07 | 0.70 | 4.01 | 2.12 | 3.06 |
| stl | -0.20 | -1.54 | 3.56 | 2.80 | 4.04 |
| blk | -0.04 | -0.92 | 3.93 | 2.32 | 2.92 |
| tov | 0.17 | -1.16 | 4.66 | 3.03 | 3.35 |
| fg_pct | 0.42 | -0.78 | 4.19 | 2.82 | n/a |
| ft_pct | -0.10 | 0.20 | 4.15 | 3.66 | n/a |

* **Spread.** The league's sigma is narrower than the simulated one in every category: 9 %
  narrower in points, 12 % in free throws, 45 % in rebounds and 47 % in assists. The standings
  sit between the two in five of the seven categories they can measure (threes, rebounds,
  assists, blocks, turnovers). In points they match the simulation (3.58 against 3.54), and in
  steals they are wider than both.
* **Mean.** The league's rosters sit below the z pool in steals, blocks, turnovers and field
  goal percentage, and above it in assists and points. The pool is the top 156 by total z, so a
  mean below it is what drafting by the market rather than by z would leave. One draft cannot
  say whether that is the league's habit or this year's market.

## 2. The 2026-10-14 roster on each curve

The user's 13 players, the two keepers included. Each cell is the chance of beating a team
drawn from the league, with the category's call.

| cat | simulated curve | league curve |
|---|---|---|
| pts | 0.16 (contested) | 0.10 (conceded) |
| threes | 0.75 (contested) | 0.85 (secured) |
| reb | 0.37 (contested) | 0.33 (contested) |
| ast | 0.24 (contested) | 0.05 (conceded) |
| stl | 0.74 (contested) | 0.90 (secured) |
| blk | 0.58 (contested) | 0.76 (contested) |
| tov | 0.82 (contested) | 0.97 (secured) |
| fg_pct | 0.19 (contested) | 0.19 (contested) |
| ft_pct | 0.42 (contested) | 0.38 (contested) |
| **expected categories won** | **4.26** | **4.54** |

* On the simulated curve every category is contested. On the league curve three are secured
  (threes, steals, turnovers) and two are conceded (points, assists): the narrower spread turns
  the roster's leads and deficits into near-certainties.
* The 4.26 is the night's corrected D5 (the master's analysis of 2026-10-14). The 4.54 is
  in-sample: the league curve was fitted on these twelve rosters, the user's among them.

## 3. The plan at the user's first pick (overall 4)

Simulated curve:

| rank | candidate | cost vs best (categories won) |
|---|---|---|
| 1 | Amen Thompson | 0.000 |
| 2 | Dyson Daniels | 0.045 |
| 3 | Tyrese Maxey | 0.181 |
| 4 | Jamal Murray | 0.218 |
| 5 | Donovan Mitchell | 0.222 |
| 6 | Kevin Durant | 0.240 |

Planned picks: 4 Amen Thompson, 21 Dyson Daniels, 52 Ausar Thompson, 69 Isaiah Hartenstein,
93 Collin Murray-Boyles, 100 Neemias Queta, 117 Paul Reed, 124 Yves Missi, 141 Isaiah Jackson,
144 Cason Wallace, 148 Joan Beringer.

League curve:

| rank | candidate | cost vs best (categories won) |
|---|---|---|
| 1 | Cade Cunningham | 0.000 |
| 2 | Luka Doncic | 0.142 |
| 3 | Amen Thompson | 0.234 |
| 4 | Dyson Daniels | 0.257 |
| 5 | Jamal Murray | 0.309 |
| 6 | Donovan Mitchell | 0.361 |

Planned picks: 4 Cade Cunningham, 21 Dyson Daniels, 52 Ausar Thompson, 69 Isaiah Hartenstein,
93 Collin Murray-Boyles, 100 Yves Missi, 117 Moussa Diabate, 124 Neemias Queta, 141 Gui Santos,
144 Oso Ighodaro, 148 Isaiah Jackson.

Each plan's final roster (drafted, kept and planned), scored on both curves:

| plan | on the simulated curve | on the league curve |
|---|---|---|
| simulated plan | 4.81 | 4.99 |
| league plan | 4.69 | 5.33 |

* **The first pick changes.** The simulated curve takes Amen Thompson, with Dyson Daniels
  inside the 0.05 tie band. The league curve takes Cade Cunningham, with Luka Doncic (the user's
  pick on the night) second, 0.14 behind. On the league curve, Thompson is 0.23 behind; on the
  simulated curve, Doncic is not in the top six.
* **The middle rounds agree.** Picks 21, 52, 69 and 93 are the same four players under both
  curves (76 is a keeper). From pick 100 the plans share only Neemias Queta, Yves Missi and
  Isaiah Jackson, at different picks.
* **Each plan is best on its own curve.** The simulated plan gives up 0.34 categories on the
  league curve; the league plan gives up 0.12 on the simulated one. The narrower curve punishes
  the wrong plan almost three times as hard.

## Reading

* The league's drafted rosters are narrower than the simulated league in every category. The
  standings, a noisier and independent measure over ten seasons, agree for threes, rebounds,
  assists, blocks and turnovers. The direction is the 2026-10-06 study's.
* The first-round choice is a curve question: on this board it moves from Amen Thompson to
  Cade Cunningham, and the user's own pick goes from outside the top six to second.
* Not a default. One season of twelve rosters is a small sample. The fit and the user's E[cats]
  on it are in-sample, and the means carry this draft's market as much as the league's habits.
* What would settle it: preseason projection files for past seasons. With
  `projections_<year>.csv` in the archive, the same code fits on more seasons and can be scored
  out of sample, season by season: fit on the others, score the held-out season's rosters.

Reproduce: `python scripts/league_curve.py` (20 s plan budget; `--time-limit` to change it).
