# AUTOPILOT: the prize leagues run themselves, with a Monday scorecard and a weekly hill-climb

Tracker: #127. Filed 2026-10-22 from the user's ask, in their words: "for the public prize leagues my
goal is to run them completely autonomously, or at least as close to autonomous as possible. and we
set a hill climbing process where compare actual performance in the prior week and YTD versus
project at the various times we made waiver moves. then analyze for strategies to improve,
implement early Monday morning, then repeat the next week."

The private league is different, in the user's words: "my private league we utilize the
improvements but all moves need to be made manually by me. so you make the suggestions. i
ultimately decide and manually make the inputs." Nothing ever clicks there.

## 1. What runs where

| league | the engine | who acts |
|---|---|---|
| a public prize league the user has armed | every view, the daily moves solve, the lineup, the scorecard | the extension, in the user's own Chrome, inside the guardrails below |
| a public league the user has not armed | the same | nobody; the dashboard shows the recommendations |
| the private league | the same | the user, by hand, from the Waivers, Strategy and Lineup views and the daily digest |

Arming is per league and is the user's own click on the dashboard, recorded in
`data/leagues/<id>/armed.json` as the draft's arming was (#67). The user armed every public
league in advance (2026-10-22), so a public league counts as armed unless the user disarms it on
the dashboard; the private league cannot be armed. A disarmed league is never touched. A file `data/autopilot/STOP` stops every executor at once; a session that sees it does
nothing and says so.

Every public league folder today (twelve) has the same waiver rules, read from Yahoo's public
settings: continuous waivers, a two-day waiver period, FAAB, four adds a week, the trade deadline
2027-03-04. The rules are read, never assumed, since a league can differ.

## 2. The rule change, and the guardrails that come with it

The standing rule that nothing clicks Add, Drop or Trade in Yahoo is lifted for Add, Drop and the
lineup, in an armed public league only (user, 2026-10-22). Trades stay suggestions everywhere.
The executor is the extension's content script on the league's own pages, the way the armed draft
clicked Draft, with the user's session and nothing typed by any Claude session. Yahoo's terms
frown on automated account actions; the user authorizes this per league, as they did the draft.

Guardrails, all of them required before the first real click:

- **A dry-run week first.** The executor logs what it would have clicked, with the page it saw,
  for a full week on the armed leagues before it clicks anything, and the log is reviewed.
- **The veto window.** The day's recommended moves are queued at a fixed time and executed an
  hour later unless the user strikes one from the dashboard (user, 2026-10-22). The queue shows
  each move with its projected gain, its FAAB bid and the lineup it implies. A lineup change
  needs no window: it is reversible until tip-off.
- **Caps.** The league's own add limit; at most two executed moves per league per day unless the
  user raises it; a move whose projected gain is below the week's noise floor (set in phase 2 from
  the scorecard) is not executed, only shown.
- **The keep rule** (section 4): the executor never drops a protected player.
- **Idempotence.** Before any click the executor re-reads the page: the player must still be
  available, the drop still on the roster, the add count still under the limit, the queue entry
  not struck. A page that does not match is logged and skipped, never forced.
- **The log.** Every click, the page state before and after, and the outcome go to
  `data/leagues/<id>/autopilot/<date>.json`; the daily digest's summary line counts them.
- **Never the private league, never a trade, never a sign-in.**

## 3. The weekly loop

Times are the Mac's clock (Pacific). The routines are the master's to edit; sessions never edit
them.

| when | what | exists |
|---|---|---|
| daily 05:00 | Basketball Monster exports, public refresh, breakout digest on #99 | yes (`breakout-digest-daily`) |
| daily, after the refresh | the moves solve per league writes its decision-log entry (#125); the queue is built from the armed leagues' recommended sets; the lineup for today and tomorrow is set | phase 1, 2 |
| daily, an hour later | the queue is executed, less what the user struck | phase 2 |
| Monday 06:00 | the recorder writes last week (#97) | yes (`weekly-recorder-monday`) |
| Monday, after the recorder | the scorecard (#126): last week and YTD, projected against actual, posted on #127 | phase 0 |
| Monday, after the scorecard | the hill-climb step (section 6): one change applied, logged on #127 | phase 3 |
| Monday, then | the week's first queue is built under the new setting, before the first claims | phase 2 |

## 4. The strategy rule (user, 2026-10-22)

"It is fine to add/drop fringe players based on having only 2 games when a waiver option has 4
for example, but it doesn't make any sense to sacrifice the season by dropping a net positive
player that's better than any waiver pickup just because he plays few games or has an injury
for 3 or 4 weeks (should be IR spot for him). So you will have to figure out who to add/drop
from IL if the IL spots are full also."

In the model's terms, carried by #124:

- A rostered player is **protected** when he is net positive (his rest-of-season per-game value
  is above the pool's average under the league's scorer), that value exceeds the best available
  add's by the protection floor (section 6), and he returns this season (an Out For Season player,
  or one listed INJ, SUSP or NA with no return date, is not protected; an O without a date returns
  next Monday). Both values are Basketball Monster's rest-of-season line whatever system the solve
  runs on: Yahoo's values are week projections. A protected player is never a drop candidate on
  any horizon or strategy weight, whatever his games this week and whatever his absence. The
  three-week horizon and the season extrapolated from it value a player out three weeks at about
  nothing, so the rule is a forced keep, not a value term (ruled 2026-10-22).
- A protected player who is out goes to IL when Yahoo's rule makes him eligible (Out or Out For
  Season; see `docs/ADD_DROP.md`) and a slot is open. The stash is worth it when the freed spot's
  best add over the horizons beats what he gives after his return; the engine shows both. Several
  eligible players for fewer open slots: the latest to return goes first, roster order breaks ties.
- A player's value net of return is (his per-game value above an empty line, under the scorer
  that valued him) times his games from his return to the season's last day, from the schedule
  where it is read and his team's rate over the read days where it is not. It is shown for every
  protected player who is out, so a long absence's cost is visible, and it ranks the IL.
- When the IL is full, the engine says who leaves it, only while an active player is eligible for
  the slot: a cleared occupant first (activated, the weakest active player dropped), else the
  occupant with the least value net of return, dropped. The ranking governs on the IL even for a
  protected occupant, who is marked as such there; the executor still never drops him.
- An absence shorter than a week keeps a player on the bench, not on waivers: a player who is
  better than the best available add over the rest of the season and returns within seven days is
  not a drop candidate for that solve, protected or not. A replacement-level player out for a few
  days is streamed like any other.
- Streaming runs among the spots below the waiver replacement level only.

The Waivers table and the Moves card say which players are protected and why; the executor reads
the same flag.

## 5. FAAB

FAAB is the Free Agent Acquisition Budget: in these leagues a claim on a player still on waivers
(the two days after he is dropped, and every player at the start) is a sealed bid from a budget
each team gets for the season, the highest bid wins, ties go to waiver priority, and a player who
has cleared waivers is added for nothing at once. The budget left is the "$" column on the
league page.

The default rule, until the user sets another or the hill-climb tunes it within these bounds:

- a free agent (cleared waivers) is added at once for $0;
- a claim's bid scales with the move's projected gain relative to the week's typical
  recommended gain: $1 for a routine stream, more for a flagged breakout or a move that lifts
  the week's odds by a lot;
- no ceiling (user, 2026-10-22: valuable waiver pickups early in a season-long league are
  rare); the bid is sized to the move's value and the budget left, and the hill-climb may tune
  the sizing;
- the bid and its reason go in the queue, so a veto can strike the bid, not only the move.


## 6. The hill-climb

**The metric.** For each executed move, the realized gain: the added player's actual line from
the move's date to the end of the horizon against the dropped player's over the same days, in
the units the move was valued in, summed YTD and compared with the projected gain at decision
time. Ruled 2026-10-22 on #126: the realized gain of a move is the added player's actual games in
the span less the dropped player's, valued in the league scorer's units (fantasy points, or the
z-sum net of an empty line) by the scorer of the decision log entry itself, on both horizons,
every game the two played counting; the actual lines come from ESPN's public box scores. The
set's expected categories stays the headline beside it. Beside it: the week odds' Brier score pooled across leagues, actual wins against expected,
and the standings. The scorecard (#126, docs/ADD_DROP.md "Scorecard") computes all of it from
the decision log (#125) and the recorder (#97).

Ruled 2026-10-23 (#143, #144): every move is judged on the horizon its set was recommended for,
everywhere the scorecard speaks (the summary, the sentences, the Monday markdown, the Progress
screen's tiles and Moves view): the week's set and the streaming plan on the week, the three weeks'
set on the three weeks after, the strategy's set under the week weight on the week, its even and
natural sets on the three weeks after, its set solved under the season weight on the season once that
horizon exists, a move with no projection of its own on the week. The season is what counts: a move that wins its week can still cost the season, so every move also carries a
season horizon (its projection from the move's day to the regular season's last day, games from the
schedule as far as read and extrapolated beyond it, and its realized value so far), shown beside the
judging figure, never in its place; a move whose recommended-horizon gain is positive and whose
season projection is below minus the protection floor is flagged season-costly, and the scorecard
counts those and how many of them realized below zero. The check measures the keep rule; it does not
change the engine.
Every recommendation and comparison in the dashboard shows that season figure beside its two
horizons as the ROS column (#151), the same number the scorecard judges a move by; nothing ranks
on it.

Refined 2026-10-23 (#143, master's reading of the ruling's principle): a strategy set is judged by
its weight. The week weight (λ = 1, this week alone) is judged on the week. The even and natural
weights are judged on the three weeks after. The season weight is judged on the season.

The details (#144, plan ruled on the issue 2026-10-23; docs/ADD_DROP.md "Scorecard"):
- **The season's end.** The calendar's last day: the league's, the playoffs included, the day the
  keep rule's `games_left` counts to.
- **The games.**
  - On the week's and the three weeks' days, those horizons' own counts.
  - After them, from the day the player is back as the keep rule reads it:
    - on a day the schedule was read, his team's games;
    - on a day it was not, his team's games a day over the read days. These are extrapolated
      and counted in `extrapolated_games`.
  - Never the player's own three-week games, which are zero while he is out.
- **The flag.** `season_costly` is set at decision time when both hold:
  - the projection's value on the judging horizon is above zero;
  - the season projection is below minus the per-game floor times the dropped player's season
    games.

  Both figures are in the league's units.
- **In the Monday markdown.** Counts and ratios only: no season sum, as for every value in
  scorer units.

**The knobs**, each with bounds the Monday step may move within:

| knob | where | bounds |
|---|---|---|
| projection system or blend weight | the moves solve | bbm, yahoo, blend 0.25 to 0.75 |
| horizon weight | the strategy objective | even, natural, season |
| the protection floor | the keep rule | the margin by which a player must beat the best add; at or above the default, never below it (#150, ruled 2026-10-23) |
| the streaming floors | the streaming plan (#136) | the margin by which a plan's week must beat the set's, in a categories and a points league |
| the stash threshold | #124 | the margin by which the freed spot must beat the return |
| the FAAB sizing | section 5 | the sizing rule only; no ceiling |
| the daily move cap | section 2 | 1 to 3 |

**The protocol.** One knob changes per week, pooled across the armed leagues; where the leagues
allow it, half of them take the change and half keep the setting (A/B), since nine to twelve
matchups and some twenty moves a week are noise enough to chase ghosts (the draft edge audit in
`docs/analysis` found the within-draft "edge" was an artifact). A change is judged on the next
two weeks and YTD, reverted when worse, and every change, its reason and its result is a comment
on #127. The master applies the change (user, 2026-10-22: "you apply the rules"); the user can
override any of it afterwards: the live settings are `data/autopilot/knobs.json`, per league
where the user wants it, shown read-only on the Progress view (below), changed by the master in the session when the
user asks, and a knob the user has set is frozen until they free it.

**The Progress view** (user, 2026-10-22: "a separate module in the pickandroll UI that shows the
hill climb analysis and progress over time. some charts and graphs and also some narrative around
what is working and what isn't and what decisions were made and maybe actionable items ... although
i don't want any user inputs there ... we can handle action items in the session"). A screen of its
own at `/progress`, read-only: no form, no editable knob, no button beyond navigation. It reads the
decision log, the scorecard, the knob file and the Monday notes (`data/autopilot/notes/<monday>.md`,
sections "What is working", "What is not", "Decision", "Action items": the text the hill-climb step
also posts on the tracker) and shows, per week since the first Monday, pooled and per league:
expected against actual wins and categories; the moves' projected against realized gain, per move
and cumulative; the week odds' Brier score and the category odds' hit rate by bucket; the standing
in each league; and the knob changes as events on every chart (the Monday, the knob, the leagues
that took it, the verdict two weeks later). The narrative is generated sentences from the numbers
beside the Monday notes; the newest note's action items are listed at the top, for the session to
act on. The private league is shown apart. Built after #125 and #126, with phase 3.

**The knob file** (`data/autopilot/knobs.json`, #129). JSON the master writes, by hand until the
Monday step of phase 3 does, and the Progress view only reads. It is meant to be edited by hand, so
the view reads it leniently: a key it does not know, or a change without a date or a knob, is
named in the view's problems and left out; a verdict or source of neither kind is named there and
the change kept with none; none of it fails the page.

- `in_force`: the value in force of each knob, by the names the decision log records them under
  (#125, `knobs` in an entry) and no other: `system` and `blend` (the projection system or blend
  weight), `horizon_weight`, `protection_floor`, `plan_floor_cats` and `plan_floor_points` (the
  streaming floors), `stash_threshold`, `faab_sizing` and `daily_cap`.
- `leagues`: by league id, the knobs whose value there differs from `in_force`: the half of a
  change that kept the setting, or the user's own value.
- `frozen`: by league id, the knobs the user set and has not freed.
- `changes`, one a change: `id` (K1, K2, ...), `monday` (the Monday it started, YYYY-MM-DD),
  `knob`, `from`, `to`, `leagues` (the half that took it, by league id), `source` (`master` or
  `user`), `reason`, `decided_at` (a time), `verdict` (`kept`, `reverted`, or null while it is
  judged), `judged_on` (the Monday it was judged) and `rolled_out` (the Monday a kept change
  reached every league).

```json
{
  "in_force": {"system": "bbm", "blend": 0.5, "horizon_weight": "natural", "daily_cap": 2},
  "leagues": {"100001": {"blend": 0.6}},
  "frozen": {"100002": ["horizon_weight"]},
  "changes": [
    {"id": "K1", "monday": "2026-11-09", "knob": "blend", "from": 0.5, "to": 0.6,
     "leagues": ["100001"], "source": "master", "reason": "...",
     "decided_at": "2026-11-09T06:12:00-06:00", "verdict": null, "judged_on": null,
     "rolled_out": null}
  ]
}
```

**The Monday notes** (`data/autopilot/notes/<monday>.md`, #129). Markdown, the text the hill-climb
step posts on #127: an optional first line `posted: <time>`, then four sections headed `## What is
working`, `## What is not`, `## Decision` and `## Action items`, the last a numbered list (a line
that continues an item is joined to it). The view shows a note under the week its Monday starts,
as the note of the week before, and lists the newest note's action items at the top. A file not
named for a date, or a section of another name, is named in the problems.

**`GET /progress`** (#129, `api/season_progress.py` and `season/progress.py`) reads every league's
scorecard (#126) over all its recorded weeks, the knob file and the notes, and writes nothing:

- the season's weeks to this one;
- each league's week rows, the private league's among them (`public` false, never pooled): the odds
  of winning the matchup against the result, the categories expected against won, the Brier score,
  the standing after it, the week's moves (by group, their value projected and realized on the week,
  the scored ones compared on their judging horizon once it is over, the FAAB paid) and the
  lineup's games lost (null:
  not recorded yet), each with its running sums to it;
- the public leagues pooled by week, the same, with the category odds' buckets of the week, and the
  calibration over the season;
- every move, with its league, its players' names, the knobs in force at the entry it matched, its
  projection and its realized value split by category;
- the knob file as read, each change placed on its week with its A/B halves over the weeks it is
  judged on (from its Monday, two of them as far as recorded): the wins above expected a league,
  the moves a league a week, the standing places climbed, the Brier score and the scored moves'
  realized value against their projected, and each week's wins above expected a league for both
  halves;
- the notes, and the newest note's action items;
- the sentences, written by rule (`season/progress.py`): the pooled wins track their expectation
  within a game, else are ahead or behind by the gap; a league a game or more off its own is named;
  the scored moves track their projection when they realized within 10% of it, else trail or beat
  it; by scoring, how many of the moves checked against the season were flagged season-costly and
  how many of those realized below zero so far (#144); the matchup odds' Brier score; a bucket of
  30 category odds or more off its results by 5 points or more reads over-confident (the results
  nearer a coin flip than the odds) or timid; and each change kept, reverted or pending with when
  it is judged;
- the problems met reading the two files, and the leagues whose scorecard failed.

A move's values are in its league's scorer's units, fantasy points or the categories' z-sum, so the
moves are pooled by scoring and never summed across the two; their realized share of the projection
compares across them.

**The screen** (#129, `web/src/components/ProgressScreen.tsx`, the arithmetic in `progress.ts`) is
the league page's shell: the views in a drawer at the left, the cards in a two-half panel at the
right with their rail, the same keys (`?` lists them), and nothing that writes. It is reached from
a line under the landing page's league grid and from `p` on a league page; a league opened from it
comes back to it.

- **Trend** (`t`): the scope (the public leagues pooled, or one league, the private one among them)
  and the metric (wins, categories, or the standing), and a week range stepped with ‹ ›. Three
  figures over the range: the record against the wins expected (or the categories, or the place);
  the scored moves' realized share of their projection, each on its judging horizon, one share for
  each unit with its sums beside it, never one sum across the two; and the Brier score last week
  and over the range.
  Then the scope's sentences, the chart (actual solid, expected dashed, both summed over the
  range; the standing alone; each knob change a mark on the time axis that opens its sheet; a
  tip by week, with each league's result when pooled), the week strip, and the league table
  (W-L, expected, the gap, moves, realized in the league's units, lineup games lost shown as a
  dash until the lineup log exists, the place), each row opening its weeks.
- **Moves** (`m`): the same scope and range, and the moves made by match (as recommended,
  differently, not recommended, no solve before it), each counted. Each move is judged on the
  horizon its set was recommended for (the week's set, the streaming plan's and the strategy's
  week-weight set on its week, the three weeks' set and the strategy's even and natural sets on the
  three weeks after, the strategy's season-weight set on the season), in its league's units. Four figures: projected and realized over the moves
  whose horizon is over, one for each unit, with the realized share of the projection; the season
  check (#144), the moves flagged season-costly of those checked and how many went below zero so
  far; and the FAAB paid, free against bid. Then the scope's moves sentences (the season check's
  among them), a chart of the realized against the projected summed to each week (one unit at a
  time, switched when both are present; the knob changes marked), and the table: date, league,
  add, for, horizon, bid, match, projected, realized ("so far" while the horizon runs), the gap
  once it is over, and the season beside them, never in their place (projected to the season's
  last day, realized so far, a "costly" mark for a flagged move; its tooltip gives the games, read
  and extrapolated). A row opens the move in card 3; ▸ opens its categories under it, a bar for
  the realized and a tick for the projected on one scale around zero.
- **Odds** (`o`): the matchup odds by their Brier score over the range (0.25 a coin flip, lower
  better), the record against the wins expected, and the category odds' share won against the
  odds said; the odds sentences; the Brier score by week against the coin flip, the knob changes
  marked; and the category odds by bucket over the range (the odds said, the categories, the
  share won and the gap). The buckets are the public leagues pooled whatever the scope: a league
  alone holds too few categories to read.
- **Table** (`b`): every league by week, the newest first, each week under a row with the public
  leagues' record against expected and the changes that started in it: the result, its odds, the
  gap, the categories against expected, the moves, their realized value and the place.
- **Cards:** 1 Note (one Monday note at a time, stepped with ‹ ›: the action items first, as
  handled in the session, then what is working, what is not and the decision), 2 Knobs (the
  changes with their half and verdict, the knobs in force, each league's own values and the knobs
  frozen, and any problem reading the files), 3 League (the league chosen: its record, place, its
  moves' realized share on their judging horizons, moves by match and sentences, and a link to its
  league page), or the Move in the Moves view (the
  move chosen: its projected and realized values, horizon and bid, its season figure, how it
  matched the solve and from which set, when it was solved and made, the knobs in force at that
  solve, its week's result and the set's odds of winning the matchup and expected categories
  before and after it, and over the season its projection with the games and its realized value
  so far, with the season-costly flag or the check's clearing), and
  4 Odds (the season's Brier score and the category odds by bucket, the public leagues pooled,
  with the odds sentences).
- **The knob sheet**, over the view (Esc closes it, ← → step through the changes): the change and
  its dates, its verdict as the file holds it, the wins above expected a league a week for A
  against B, the A/B table, why it was tried (the Decision of the note of its Monday, else the
  change's reason), the rule it is judged by and the leagues in A.

## 7. Phases

- **Phase 0, measurement, no clicks.** #125 the decision log and the transactions reader; #126
  the Monday scorecard with its markdown for #127. The Monday routine gains the scorecard step
  once #126 is merged.
- **Phase 1, lineups.** #107 and #124 first (the lineup route, the Lineup view, the IL rules and
  the no-drop add). Then the extension sets the lineup for today and tomorrow in an armed league
  from the lineup route's per-day slots: the first executor, reversible until tip-off.
- **Phase 2, moves.** The queue, the veto window, the dry-run week, the caps, the FAAB rule, the
  executor for Add and Drop with the idempotence check, the autopilot log and the digest line.
  Filed when phase 1 is in.
- **Phase 3, the hill-climb step.** The Monday analysis over the scorecard, the knob file, the
  A/B split, the revert rule, the comment on #127. The Progress view of
  section 6, the Monday note it renders. Filed 2026-10-23 as #152, before two scored weeks, at the user's direction ("don't wait, we will work out the kinks as we go"); the engine reading the knob file is part of it.

## 8. What is never committed

Everything under `data/` stays local: the decision logs, the autopilot logs, the knob file, the
armed files, the transactions parts. Public text (issues, PR bodies, the scorecard's markdown on
#127, docs) carries player names, league ids and aggregates, never a Yahoo team or league name and
never a Basketball Monster number.

## 9. Decisions taken with the user

- 2026-10-22: the goal and the loop, in the user's words above. The private league is
  suggestions only. The extension may add, drop and set lineups in an armed public league. Moves
  go through a veto window. The master applies the Monday change; the user can override later.
  The strategy rule of section 4.
- 2026-10-22, later: no FAAB ceiling. Every public league is armed in advance; only the private
  league is excluded.
- 2026-10-22, evening: the hill-climb gets a read-only Progress view of its own (section 6):
  charts, narrative, decisions and action items, no inputs; action items are handled in the
  session.
- 2026-10-22, night: the keep rule as section 4 reads (#124, a forced keep on every horizon); the
  scorecard's realized gain per move in scorer units from ESPN's box scores, every game counting
  (#126).
- 2026-10-23, night: every move judged on its recommended horizon everywhere (#143); the season
  horizon, the season check and its flag (#144), the season being what counts.
- 2026-10-23, morning: the lineup-lost count is counted (#149); the protection floor has a minimum
  the hill-climb may not go below, the default (#150); phase 3 is filed now, not after two scored
  weeks (#152); every move and trade recommendation and comparison shows the rest of the season
  beside the week and the three weeks (#151). The test hygiene issues #121 and #122 build. The
  season dashboard gets a freshness light for the daily updates and shorter header text (#153).
  Multi-step plans cover the current week only (the streaming plan, #136); a sequence of moves
  over several weeks is never built: "too many unknowns".

