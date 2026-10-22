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
`data/leagues/<id>/armed.json` as the draft's arming was (#67). A disarmed league is never
touched. A file `data/autopilot/STOP` stops every executor at once; a session that sees it does
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

- A rostered player whose rest-of-season value (the season horizon at the natural weight)
  exceeds the best available add's is **protected**: never a drop candidate on the week horizon,
  whatever his games this week.
- A protected player who is out goes to IL when Yahoo's rule makes him eligible (Out or Out For
  Season; see `docs/ADD_DROP.md`) and a slot is open. The stash is worth it when the freed spot's
  best add over the horizons beats what he gives after his return; the engine shows both.
- When the IL is full, the engine ranks the occupants by rest-of-season value net of return and
  says who leaves it (a drop, or a cleared occupant to activate) and what that frees.
- An absence shorter than a week keeps a player on the bench, not on waivers.
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
- no single claim bids more than 20% of the budget left, and no week more than 35% of it;
- the bid and its reason go in the queue, so a veto can strike the bid, not only the move.

Open: the user's own ceiling, if they want one other than these.

## 6. The hill-climb

**The metric.** For each executed move, the realized gain: the added player's actual line from
the move's date to the end of the horizon against the dropped player's over the same days, in
the units the move was valued in, summed YTD and compared with the projected gain at decision
time. Beside it: the week odds' Brier score pooled across leagues, actual wins against expected,
and the standings. The scorecard (#126) computes all of it from the decision log (#125) and the
recorder (#97).

**The knobs**, each with bounds the Monday step may move within:

| knob | where | bounds |
|---|---|---|
| projection system or blend weight | the moves solve | bbm, yahoo, blend 0.25 to 0.75 |
| horizon weight | the strategy objective | even, natural, season |
| the protection floor | the keep rule | the margin by which a player must beat the best add |
| the stash threshold | #124 | the margin by which the freed spot must beat the return |
| the FAAB sizing | section 5 | within the caps above |
| the daily move cap | section 2 | 1 to 3 |

**The protocol.** One knob changes per week, pooled across the armed leagues; where the leagues
allow it, half of them take the change and half keep the setting (A/B), since nine to twelve
matchups and some twenty moves a week are noise enough to chase ghosts (the draft edge audit in
`docs/analysis` found the within-draft "edge" was an artifact). A change is judged on the next
two weeks and YTD, reverted when worse, and every change, its reason and its result is a comment
on #127. The master applies the change (user, 2026-10-22: "you apply the rules"); the user can
override any of it afterwards: the live settings are `data/autopilot/knobs.json`, per league
where the user wants it, shown and editable on the dashboard, and a knob the user has set is
frozen until they free it.

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
  A/B split, the revert rule, the comment on #127. Filed when phase 0 has scored two weeks.

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
