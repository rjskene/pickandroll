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

The lineup executor (#170, ruled on the issue 2026-10-23) is the first to run under these. Its API
side (PR 1) is in `api/season_autopilot.py`; the click is the extension's, on the team page:

- **The mode.** `armed.json`'s `lineups` key, `off`, `dry_run` or `live`, with when and by whom
  it was set (`PUT /leagues/{league}/lineups`, the Lineup view's switch). An armed public league
  starts in `dry_run`; the private league is always `off` and refuses the switch. Disarming the
  draft keeps the mode, and an `armed.json` holding only the mode reads as not armed.
- **The live guard.** `live` is refused until the league's log holds dry-run lineup runs on seven
  distinct days, on two of them a run whose steps all passed every check of the page, and STOP is
  absent. The review on #127 and the user's own click are the other two gates; no code sets it.
  Live itself (the submit) is PR 3, after the dry-run week; nothing in PR 1 or PR 2 clicks.
- **STOP.** The file `data/autopilot/STOP` stops every executor: the steps answer `stop: true`
  with none, the log takes only a run that says it stopped, the view and the digest say so.
  Nothing in the code writes it; the user creates or removes it by hand.
- **The steps.** `GET /seasons/{league}/lineup/steps?date=` turns Yahoo's lineup as read into the
  recommended one for the day, from the Lineup view's own day (nothing is solved again): a list
  of single moves, each legal on its own, in groups that share no player and no slot. A group
  touching a player whose game has begun (the tip from the schedule copy) is dropped whole into
  `skipped`; the rest are ordered by the earliest tip. Held slots are never touched.
- **When it runs.** On the daily routine's fragment `#pickandroll-lineup` or the side panel's
  button, never on a page load of its own (`trigger`: `routine`, `routine_late`, `panel`).
- **The page check (PR 2, extension 0.6.0).** A run posts the team page, then takes the steps only
  when they were built from that post (`read.at` is the post's time) and the page's lineup is the
  one they read (`yahoo`). The page must be my team's own editable lineup form for the steps' day.
  Each step is checked on the form: the player in the step's slot with a select (a hidden field is
  a locked player), the target among his options, the player swapped back able to take the step's
  slot, or the target open (`slots`). A group with a failing step is skipped whole. The run logs
  the form's action and field names (never a value, never the crumb's), each moved player's
  control and the select values it would set; it sets nothing. The settings page's "Lineup
  executor in this browser" is the browser's own brake beside STOP.
- **The log.** `POST /seasons/{league}/autopilot/lineup` appends one run to
  `data/leagues/<id>/autopilot/<date>.json` as `{"lineup": [...]}`, the only writer there; phase 2
  adds `moves` beside it, and a run never rewrites another. A run carries the page it read, the
  form's field names (never a value), the lineup before and after and each step's outcome. A run
  carrying the page's crumb is refused (422), as are a dry run that says it set something, a live
  run outside live, and any run but a stopped one under STOP or with the mode off (409). A log
  file that does not read is refused, never overwritten.
- **The digest.** One line for the executor in the Lineups section (the leagues in dry run, how
  many had steps, how many none, how many did not run, the day-runs that would set, were
  skipped, failed), then a line per league only for a skip or a failure. Under STOP the line says
  nothing runs.

The moves executor (#171, ruled on the issue 2026-10-23) follows. Its API side (PR 1) is the queue
in `season/autopilot.py` (pure) and `api/season_queue.py`; the claim is the extension's, on the add
page, from PR 2:

- **The queue.** `POST /autopilot/queue/build` (the end of the 05:00 routine, again after the
  Monday hill-climb) takes each armed league's last moves solve of the day from the decision log
  and its three weeks' set (`three`, season first); it never solves, and a league not solved that
  day says so. Every move of the set is an entry with the set, the decision and the knobs in
  force, queued or with the first reason it is not: the private league or the mode off; a drop
  the keep rule protects (read from the engine, never re-solved); a move flagged season-costly; an
  add the league dropped within the waiver days (or one the set drops); below the noise floor; no
  adds left in the week of its clear date; over the day's cap. The rest are queued by their gain
  on the three weeks after, highest first. The streaming plan stays a dashboard suggestion.
  `data/autopilot/queue/<date>.json` holds the day; nothing else writes it. Each entry carries its
  move's `basis` (`open`, `held` or `drop`) and `held_move`, the held-slot move a `held` add needs
  (#187; null when the decision log entry was written before #187). The live claim (PR 3) reads
  them: a `held` add executes after its held move, never as an open-spot claim.
- **The noise floor.** The plan floor of the knobs against the move's gain; once 20 moves are
  scored, also the scorecard's spread (the standard deviation of realized less projected value of
  the public leagues' scored moves, by scoring) against the move's value on its judging horizon,
  in the scorer's units. The scored floor never lets a move through below the plan floor: a move
  clears both, and the entry names both figures and which one stopped it.
- **The veto window and the execute time.** An entry executes at the later of an hour after it was
  queued and the day's execute time (09:00 Pacific until the user sets another on the landing
  page's Queue line, `PUT /autopilot/queue/settings`; the day's entries not executed are timed
  again, never inside their hour). The Queue card (9) strikes an entry or its bid alone (a $0
  claim) or undoes either, until it executes (`POST /autopilot/queue/{id}/strike`). A rebuild
  the same day keeps the struck and executed entries by id, leaves their moves out of the build,
  and gives an entry new to the queue its full hour.
- **The caps.** The league's add limit, each claim counted in the week of its clear date from
  the moment it is placed (a claim placed and not yet processed counts, won or not; the next
  build reads the adds used from the page and the transactions); the day's cap, the knob's
  `daily_cap` unless the user set the league's own (`PUT /leagues/{league}/moves` `{mode, cap}`).
  A placed claim is resolved `won` or `lost` from the transactions at the next build.
- **What the extension reads.** `GET /seasons/{league}/autopilot/moves/due`: the entries due now
  with the bid to place and the add page, my team, the players protected and why (the build's and
  the engine's now: the page check refuses a protected drop whatever the queue says), the claims
  still open (earlier days' placed and unresolved, and today's placed), the day's cap and how many
  of the day's entries took their place, the adds left as read less every claim since, and the
  budget; none when the mode is off, STOP is on or the day is not today. Each entry's `page` is
  its add page, `/nba/<league>/addplayer?apid=<add>` (Yahoo's own add link, a GET that adds
  nothing; no team in it).
- **The page check (PR 2, extension 0.7.0).** The routine opens the due pages: each due entry's
  `page` with `#pickandroll-moves` in a tab of its own (`#pickandroll-moves-late` for the late
  pass, trigger `routine_late`). The side panel's **Check moves now** lists the due entries as
  links with `#pickandroll-moves-panel` (trigger `panel`) for the user to open; the extension
  opens no tab. On an add page with one of those fragments the content script drops the fragment
  (a reload is a plain visit), takes the add from the address and the league from the path,
  fetches `due` and checks the one entry whose add it is; no such entry, nothing is logged. It
  fetches no Yahoo page and navigates nowhere. The checks, each a skip with its reason:
  - **The queue's:** the mode is dry run or live and STOP off; not struck; not an open-spot
    claim (not read yet); the drop not protected; no pending claim names the add; the day's cap
    not reached; the clear date's week has an add left.
  - **The page's identity:** the claim form (`form#add-drop-players-form`) posts to
    `/nba/<league>/<team>/addplayer` with the entry's league and `due.team`, carries `stage` and
    `apid`, and its `apid` is the add.
  - **The heading and the date:** the heading is "Claim Player From Waivers" and its waiver date
    is the entry's clear date. Any other heading skips with the heading's text, never `gone`.
  - **The drop:** exactly one `dpid` checkbox for it in my roster's table and no can't-cut or
    locked icon on its row; the reason names the marker found (`cantcut`, `locked` or `none`)
    and the id. Never a fallback drop.
  - **Adds left:** `due.adds_left` covers the claim and the add's row has no "no more roster
    moves" icon.
  - **The bid:** a whole dollar inside the page's "between $x and $y" and at most the budget.
  - **The submit:** the claim submit `submit_drop_player` is on the page.

  `gone` only when the page shows the add on a team (an on-team icon on the add's row, or a
  page without the form saying so); a page without the claim form is skipped "page not read",
  so the late pass retries. A pass that passes logs `would_claim` with the fields the claim
  would fill (`{action, apid, dpid, faab, submit}`), the form's other field names (the
  anti-forgery field's left out), `token` (whether the form has that field), the heading, the
  waiver date, the budget, the bid range, the adds left, my roster's can't-cut ids, the add's
  row icons and when the page was read: ids, dollars and dates only. The waiver-order table is never read. It toggles, sets and submits nothing. The
  control names are the DOM read on #171 (2026-10-24); PR 3 submits this rendered form, so the
  crumb travels only in the browser's own submission.
- **The mode, the log and the live guard.** `armed.json`'s `moves` key and `moves_cap`, like the
  lineups'. A pass is `POST /seasons/{league}/autopilot/moves`, logged under `moves` beside
  `lineup` in the league's day file. A live pass sets each entry's outcome on the queue
  (`claimed`, `added`, `skipped`, `failed`, or `gone` when another team had the add first, never
  retried that day); a dry run moves no queue outcome, so the day's entries stay due for the
  late pass and the next day's dry run. Refused: a crumb (422); a dry run that claims, a live
  pass outside live, an entry not in the day's queue, struck, already executed or naming another
  move, and anything but a stopped pass under STOP or with the mode off (409). `live` waits for
  dry-run passes on seven days, two of them checked: a pass that opened the add page and logged its controls for
  at least one entry (a pass that found nothing due is a dry-run day, not a checked one).
- **The digest.** A Moves section: the latest queue's entries queued and struck, the last day's
  entries would-be-claimed (or claimed), skipped, failed and gone, then a line per league only for
  a skip or a failure; under STOP the line says nothing runs.

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
| Monday, after the scorecard | the hill-climb step (section 6): the verdicts due and at most one change applied, the comment posted on #127 | yes (#152, `scripts/season.py monday`); the Monday routine runs it from 2026-10-26 |
| Monday, then | the week's first queue is built under the new setting, before the first claims | phase 2 |

## 4. The strategy rule (user, 2026-10-22)

"It is fine to add/drop fringe players based on having only 2 games when a waiver option has 4
for example, but it doesn't make any sense to sacrifice the season by dropping a net positive
player that's better than any waiver pickup just because he plays few games or has an injury
for 3 or 4 weeks (should be IR spot for him). So you will have to figure out who to add/drop
from IL if the IL spots are full also."

In the model's terms, carried by #124:

- A rostered player is **protected** when he is net positive (his rest-of-season per-game value
  is above the pool's average under the league's scorer), the best available add's value does
  not beat his by the protection floor or more (section 6; a higher floor protects more, #164),
  and he returns this season (an Out For Season player,
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

As built (#171, the ruling's point 3): `max(1, round(gain / typical))` dollars, doubled for a
breakout flag and tripled for a strong one, times `faab_sizing` (1.0 while it is unset), clamped
to the budget left and nothing else; a struck bid is a $0 claim. `typical` is the fortnight's
median gain on the three weeks after of the armed leagues' recommended moves, per scoring, or
the plan floor until ten such moves exist.


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
season projection is below zero is flagged season-costly, and the scorecard
counts those and how many of them realized below zero. The check measures the keep rule; it does not
change the engine.
Every recommendation and comparison in the dashboard shows that season figure beside its two
horizons as the ROS column (#151), the same number the scorecard judges a move by; nothing ranks
on it. The season guard (#164, docs/ADD_DROP.md "The season guard") draws one line on it: no
recommended set, re-solve, streaming plan or strategy set (the program's included) has a rest of
the season below zero, in every league, the private one too. A set the guard held back is named
beside the recommended one, flagged season-costly, and the decision log records it, so the
autopilot never executes a move the guard refused.

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
  - the season projection is below zero, whatever the protection floor (#164).

  Both figures are in the league's units.
- **In the Monday markdown.** Counts and ratios only: no season sum, as for every value in
  scorer units.

**The knobs**, each with bounds the Monday step may move within:

| knob | where | bounds |
|---|---|---|
| projection system or blend weight | the moves solve | bbm, yahoo, blend 0.25 to 0.75 |
| horizon weight | the strategy objective | even, natural, season |
| the protection floor | the keep rule | the margin by which the best add must beat a player to unprotect him (#164); at or above the default, never below it (#150, ruled 2026-10-23) |
| the streaming floors | the streaming plan (#136) | the margin by which a plan's week must beat the set's, in a categories and a points league |
| the stash threshold | #124 | the margin by which the freed spot must beat the return |
| the FAAB sizing | section 5 | the sizing rule only; no ceiling |
| the daily move cap | section 2 | 1 to 3 |

**The protocol.** One knob changes per week, pooled across the armed leagues; where the leagues
allow it, half of them take the change and half keep the setting (A/B), since nine to twelve
matchups and some twenty moves a week are noise enough to chase ghosts (the draft edge audit in
`docs/analysis` found the within-draft "edge" was an artifact). A change is judged on the next
two weeks, the year to date beside it, reverted when worse, and every change, its reason and its
result is a comment on #127 (the Monday step, below). The master applies the change (user, 2026-10-22: "you apply the rules"); the user can
override any of it afterwards: the live settings are `data/autopilot/knobs.json`, per league
where the user wants it, shown read-only on the Progress view (below), changed by the master in the session when the
user asks, and a knob the user has set is frozen until they free it.

**The Progress view** (user, 2026-10-22: "a separate module in the pickandroll UI that shows the
hill climb analysis and progress over time. some charts and graphs and also some narrative around
what is working and what isn't and what decisions were made and maybe actionable items ... although
i don't want any user inputs there ... we can handle action items in the session"). A screen of its
own at `/progress`, read-only: no form, no editable knob, no button beyond navigation. It reads the
decision log, the scorecard, the knob file and the Monday notes (`data/autopilot/notes/<monday>.md`,
sections "What is working", "What is not", "Decision", "Action items", which the Monday step writes;
the tracker gets the step's comment, below) and shows, per week since the first Monday, pooled and per league:
expected against actual wins and categories; the moves' projected against realized gain, per move
and cumulative; the week odds' Brier score and the category odds' hit rate by bucket; the standing
in each league; and the knob changes as events on every chart (the Monday, the knob, the leagues
that took it, the verdict two weeks later). The narrative is generated sentences from the numbers
beside the Monday notes; the newest note's action items are listed at the top, for the session to
act on. The private league is shown apart. Built after #125 and #126, with phase 3.

**The knob file** (`data/autopilot/knobs.json`, #129). JSON the Monday step writes (#152) and the
master may edit by hand, and the Progress view only reads. It is meant to be edited by hand, so
the view reads it leniently: a key it does not know, or a change without a date or a knob, is
named in the view's problems and left out; a verdict or source of neither kind is named there and
the change kept with none; none of it fails the page. A value outside its bounds (a system or
weight not among the choices, a number that is not one, a cap that is not whole, under a minimum
or over a maximum) is a problem and left out, so the default stays.

**At solve time** (#152, `api/season_knobs.py`). Every solve of the moves, matchup, season,
lineup, strategy and trade routes reads the file again and runs with the code's defaults, then
`in_force`, then the league's own values (`season.progress.in_force_for`); a missing file or one
that is not JSON means the defaults (system `bbm`, horizon weight `natural`, protection floor 0.0,
plan floors 0.10 and 0.01, daily cap 2). The solves kept for the day are keyed to the file's
version, so a change is in force from the next solve. A route's named system wins over the
file's. The engine reads the hooked knobs, `season.progress.HOOKED`: the system and the blend
weight (the moves solve), the horizon weight (marked recommended on the Strategy panel, never
executed), the protection floor (the keep rule), the plan floors and the daily cap (the streaming
plan). The stash threshold and the FAAB sizing are unhooked: recorded in the decision log as the
file has them, read by nothing, and never changed by the Monday step.

**The system scored** (#152). Each decision log entry records `knobs.file_system`: the system the
knob file had in force for its league when it was logged, beside the system the solve ran on
(`bbm` without a file; an entry logged before entries kept it counts as `bbm`). With no system
named, the scorecard and the Progress view project each week on the system in force when it
began: the last week-start entry whose `file_system` is the one the week's first week-start entry
recorded, and that was solved on it. A change of system made on a week's Monday therefore leaves
that week projected on the old system for both halves, whatever is solved after the step, and a
revert loses no A week. A named system still wins. A move with no scorer of its own borrows the
nearest entry's solved on the system in force when it was logged.

**The Monday step** (#152; `season/hillclimb.py`, pure, and `api/season_hillclimb.py`;
`POST /autopilot/monday`, `scripts/season.py monday`). It runs after the recorder and the
scorecard, on the API's own data and under one lock. The armed leagues are the public ones
(section 1). The private league takes no change; the file is written so that its values stay as
they were, and no rollout reaches it.

- **The verdicts first.** A change whose source is the master is judged once its two weeks (the
  week of its Monday and the next) are recorded; a user's change never is. A is the leagues that
  took it, B the half it recorded (`b_leagues`), each armed, of its scoring and not frozen for the
  knob. The measures, in this order, each over the two weeks, with the gap the halves must differ
  by:
  1. wins above expected a league of the half, 0.5;
  2. categories above expected a league of the half, 1.0;
  3. the half's moves' realized share of their projection on their judging horizons, pooled by
     scoring, 0.10;
  4. the season-costly moves realized below zero so far a league of the half, 1.

  The first that clears decides: kept when A did no worse, reverted when worse. A change that none
  clears is kept: A did no worse. A half of one or two leagues is as noisy as it sounds; that is the
  sample. Beside the verdict, never deciding, the year to date is read as a difference in
  differences (`since`): each measure's A − B gap to the last recorded week less its gap before
  the change (a sum over no weeks counts nothing), with the raw figures. For the sums it equals the
  window while the judgement is on time; for the share it is the share gap now less the gap before.
  A revert writes back the values the change replaced in the A leagues. A kept change rolls out all
  it set to every armed league of its scope through `leagues` (`in_force` holds a value only while
  every league shares it), and `rolled_out` is set.
- **Then at most one change**, from the first rule in this order that clears and is not blocked.
  A sample counts only scored moves whose judging horizon is over.

  | rule | knob | sample | clears when | step |
  |---|---|---|---|---|
  | the season check, per scoring | `protection_floor` | the scoring's season-costly moves (#144) | 3 or more, more than half below zero over the season so far | +0.05 z a game (categories), +0.5 fantasy points a game (points) |
  | the streaming plans, per scoring | `plan_floor_cats`, `plan_floor_points` | the scoring's plan moves (#136) | 5 or more, realized under half their projection | half its value up, never above four times the default |
  | the projection system | `system`, `blend` | the moves under the system in force, pooled across the scorings by realized share | 20 or more, realized under half their projection season to date | Basketball Monster's (or Yahoo's) to the blend at 0.5, never a flip; a kept blend 0.25 toward Yahoo's, never past 0.75 |

  Nothing reads the odds' calibration: that is the model's, not a knob's. A rule that clears is
  blocked when:
  - its knob has no hook (`season.progress.HOOKED`), so the stash threshold and the FAAB sizing
    never change;
  - the step would take the knob out of its bounds or under its minimum;
  - the knob, or the system's family (system and blend), was written in the last four weeks, by a
    change's Monday, its revert or its rollout;
  - a change of it is still being judged;
  - fewer than two leagues are left to split.

  The next rule then has its say, and the note names the rule passed over.
- **The A/B split.** The scope is the armed leagues of the rule's scoring (of both for the system),
  less those where the knob is frozen, holding the value most of them share. It splits by league
  id, alternately; the half that lagged on the rule's measure takes the change (A), the first half
  on a tie.
- **Once a Monday.** A second run answers that Monday's changes, note and comment and writes
  nothing. `force=true` undoes that Monday's own change, never one already judged, and runs again,
  rewriting the note and the comment; the verdicts judged that Monday stand. `dry_run=true` writes
  nothing and says so. A day that is not a Monday is refused (422), and so is a knob file the step
  cannot write without losing what is in it (409), which is never overwritten.
- **What it writes**, all under `data/autopilot/`: the knob file, the Monday note
  (`notes/<monday>.md`) and the Monday's comment for #127 (`comments/<monday>.md`).
  `scripts/season.py monday` prints the step's line and the note; `--comment` prints only the
  comment, for the routine to post.
- **The comment on #127.** It has five parts:
  - the armed leagues counted by scoring;
  - the rules, each with its sample in counts and ratios and whether it cleared, or why it was
    blocked;
  - the verdicts: the measure that decided, which way and past which gap, the year to date's
    direction, and the leagues reached, never a wins or categories figure (those are set against a
    projection);
  - the change, with its reason and its halves by league id;
  - what is judged next.

  No team or league name, no projection number (section 8). A dry run's comment says so in its first
  line.

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
  reached every league). The Monday step's own changes also hold `scoring` (`categories` or
  `points` for a knob changed in one scoring only, its B half drawn from that scoring),
  `b_leagues` (the half that kept the setting, the one the verdict compares A against), `rule`,
  `set` (every value it wrote: a change of system sets the blend weight beside it), `was` (by
  knob, the value it replaced in each league of A) and, once judged, `judged` (the deciding
  measure, the window, both halves' leagues and figures, the year to date's `since` with the raw
  figures beside it, and the leagues reached). The reader keeps `scoring` and `b_leagues`; the
  rest is the step's record.

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

**The Monday notes** (`data/autopilot/notes/<monday>.md`, #129). Markdown the Monday step writes
(#152), local: an optional first line `posted: <time>`, then four sections headed `## What is
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
  player-games lost to the lineup with the days read after they ended (#149; null when none
  was), each with its running sums to it;
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
  (W-L, expected, the gap, moves, realized in the league's units, the player-games lost to the
  lineup over the days read after they ended, #149, its tooltip saying how many of the range's
  days were read and a dash when none was, the place), each row opening its weeks.
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
  from the lineup route's per-day slots: the first executor, reversible until tip-off. The
  executor is filed 2026-10-23 as #170 (user: "file both"), dry run first, `live` the user's click.
  Three PRs: the API's steps, mode, STOP, log, digest line and the Lineup view's switch (section 2);
  the extension's dry run; the live submit once the dry run has logged its week.
- **Phase 2, moves.** The queue, the veto window, the dry-run week, the caps, the FAAB rule, the
  executor for Add and Drop with the idempotence check, the autopilot log and the digest line.
  Filed 2026-10-23 as #171, behind #170, before phase 1 was in, at the user's direction
  ("file both"); built after #170, plan comment first.
- **Phase 3, the hill-climb step.** The Monday analysis over the scorecard, the knob file, the
  A/B split, the revert rule, the comment on #127. The Progress view of
  section 6, the Monday note it renders. Filed 2026-10-23 as #152, before two scored weeks, at the user's direction ("don't wait, we will work out the kinks as we go"); the engine reading the knob file is part of it.
  Built 2026-10-23 in three PRs: the engine reads the knob file at solve time, with the blend
  system (#162); the Monday step, its verdicts, the rule table and the knob file's write (#163);
  the comment on #127 and these docs. The first Monday step runs 2026-10-26.

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
- 2026-10-23, afternoon (#152, the plan ruled on the issue): the blend system is built, its weight
  Yahoo's share (0.5 when unset); the strategy marks the knob's weight recommended, natural by
  default; the stash threshold and the FAAB sizing stay unhooked, and the Monday step never changes
  an unhooked knob; the first rule table runs the season check first (per scoring, a step of 0.05 z
  or 0.5 points a game), then the plan floors (never above four times the default), then the system
  (20 scored moves, a step to blend 0.5, never a flip); the Monday write is an API route with a
  script, idempotent per Monday.
- 2026-10-23, later (#152, PR 2's judging ruled on the issue): the verdict is decided on the two
  judged weeks, year to date read as the change in the A − B gap since the change's Monday, the
  raw figure shown beside; a measure decides only past a threshold a league of the half (0.5 wins,
  1.0 category, 0.10 of realized share, 1 season-costly move below zero), and a change none clears
  is kept; each decision log entry records the file's system in force when it was logged, and a week's projection is the last week-start entry solved on the system in force when the week began (the
  one its first week-start entry recorded) unless the query names a system;
  armed is the public leagues; a per-scoring change carries its scoring; the blend's later step is
  0.25 toward Yahoo, never past 0.75.
- 2026-10-23, evening (#164, the plan ruled on the issue; user: the private league is theirs to
  judge, the public leagues are hardened): the season guard holds every recommended set, re-solve,
  streaming plan and strategy set, the program's included, to a rest of the season of zero or
  more, in every league; the set it held back is named beside the recommended one, flagged, and
  logged, so the autopilot never executes a move the guard refused; the protection floor becomes
  the margin an add must beat a player by (a higher floor protects more), and the season-costly
  flag reads a season projection below zero whatever the floor; a move with no season line counts
  as zero for the guard and marks the total partial.
- 2026-10-23, evening: the two executors are filed together (#170 lineups, #171 moves) and built in
  that order ("file both"); each starts in dry run, and only the user's own click on the dashboard
  switches a league to live, after its dry-run week is reviewed on #127.
