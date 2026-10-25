# ADD/DROP: the in-season programme (waivers, breakout flag, trades)

Status: programme approved for build by the user on 2026-10-21 ("now I want to implement waiver
pickup assessment tool"). The design sketch of 2026-10-15 is kept below with its decisions
resolved; what the user still has to decide is in the last section. Issue #4 was the placeholder
for the module, #79 the trade brainstorm, #91 the in-season test the draft edge audit asks for.
The build runs under tracker #99 with one issue per phase: #92 data layer and league picker, #98 extension page reader for the private league, #93 weekly projections and the Waivers table, #94 move optimiser, #95 breakout flag, #96 trade evaluator, #97 weekly recorder (filed 2026-10-21).

## What it is for

Once the season starts the draft tool's question changes from "who do I take now" to three
in-season questions: which free agent do I add this week and whom do I drop for him; which
free agent is a long-term asset rather than a one-week streamer; and whether a proposed trade
helps. The leagues are head-to-head, nine categories, weekly matchups, so a move is worth
exactly what it does to the categories I win in the coming weeks, not what it does to a
season-long z total. The same machinery as the draft (category curve, win objective, LP over a
roster with slots) applies, with three changes: the horizon is weeks instead of picks, totals
depend on the NBA schedule, and the opponent is one known team per week rather than a population.

## Objective

Expected categories won over a horizon of W weeks, shown for two horizons side by side
(resolved 2026-10-21): the rest of this week (W = 1, the streaming view, from Basketball
Monster's "this week" projection which already carries each player's remaining games), and
three weeks (the "is he worth a roster spot" view, from rest-of-season per-game projections
times the schedule):

    sum over weeks w, categories c  of  P(my total_{w,c} > opponent_{w}'s total_{w,c})

where a player's weekly total is his per-game projection times the games his NBA team plays in
that week, on the roster slots I can actually start (Yahoo's daily lineup: ten starters, so a
day with twelve players with games wastes two). The probability comes from the weekly spread
of each category, which is far wider than the season spread the draft curve uses; it is fit
from per-game variance and games played, and re-fit from the league's own weekly box scores
once a few weeks exist (the matchup pages record every week's totals per team).

There is no season-long tie-break: in a head-to-head each-category league standings are weekly
category wins. No punts: a conceded category is an outcome, never a target.

## Inputs, as found on 2026-10-21

Yahoo's Fantasy Sports API is still refused ("This application is not authorized to perform
this action", probed read-only with the saved token on 2026-10-21; the access request of
2026-09-21 is a month old). Nothing in-season waits for it. The prize leagues are public
leagues, and Yahoo serves everything the engine needs without a sign-in:

| input | source | notes |
|---|---|---|
| league settings, current week, roster slots, waiver and add rules | `pub-api.fantasysports.yahoo.com/fantasy/v3/settings/nba/<id>` (already used by `scripts/draft_day.py`) | `current_week`, `start_week`, `end_week`, `end_date`, `weekly_deadline`, `num_playoff_teams`, and the `settings` block; no week dates and no playoff start week |
| week dates | the public team page on a date, `/nba/<id>/<team>?date=YYYY-MM-DD`, whose "Week N stats may change" line names that day's matchup week | one request per Monday of the season, cached for every league in `data/leagues/_shared/season/calendar.json` (#92); 2026-27 has 22 weeks, week 1 Oct 19-25, week 17 Feb 15-28 across the All-Star break, week 22 Mar 29-Apr 4 |
| held slots, lineup rule, playoff weeks, the injured-add rule | the public settings page `/nba/<id>/settings`, a table of labels and values | "Roster Positions" (every slot, IL, IL+ and NA included), "Weekly Deadline" (`Daily - Today`, `Daily - Tomorrow` or weekly), "Playoffs" (`6 teams - Week 20, 21 and 22`) and whether an injured free agent may be added straight to an injury slot. v3's settings name no playoff week, and the roster the season used was the league folder's, from the draft, without IL (#107, see "Held slots") |
| my lineup on a day | my team page on that day, `/nba/<id>/<team>?date=YYYY-MM-DD` | the slots filled that day; an empty IL slot is not shown. Stored as `lineup/<team>/<day>`, apart from today's roster (#107, see "Lineups") |
| standings, waiver priority, FAAB left, moves, this week's pairs and their live scores | the public league page `/nba/<id>` | the `standingstable` and the matchups module: one `li[data-target="/nba/<id>/matchup?week=&mid1=&mid2="]` per pair with both scores (`div.Fz-lg`, in mid1/mid2 order) and no categories (#116). `?matchup_week=N` shows another week's pairs; it is stored as that week's pairings, never as the league page. Read once a week ahead for the Season view's opponents: a public refresh reads every regular week after this one whose pairs it lacks, and again only while a page lists none; the private league's pages are listed by the Monday recorder (#116) |
| a matchup's week totals and score | the public matchup page in its totals view, `/nba/<id>/matchup?date=totals&week=W&mid1=A&mid2=B` | each team's category totals; a points league adds Yahoo's original and live projected points. Without `date=totals`, while games are live, Yahoo serves the Live tab, whose teams and totals load by script: it names neither team (2026-10-22). A public refresh reads every pair's page of the week, mine first (#116); a page that names no two teams skips its pair, which keeps its last read, and the refresh's `warnings.matchups` says how many pairs and why. The two teams are the header's (`#matchup-header`), else the totals table's, never the page's navigation, which on a signed-in page links to my team first; a posted page whose teams are not its URL's `mid1` and `mid2` is skipped, and a stored matchup whose pair the league page does not list for its week is not read and is dropped at the next save (2026-10-22) |
| player pool: positions, NBA team, injury status and note, season stats, Yahoo ranks, ADP | `.../v3/players/nba/<id>?format=json&projected=1&average=1` (744 players) | `inj`, `inj_full`, `inj_note`, `display_pos`, `season_stats`; no per-league ownership |
| team list | `.../v3/teams/nba/<id>` | names and ids only |
| each team's roster, including mine and this week's opponent's | the public team page `basketball.fantasysports.yahoo.com/nba/<id>/<team>` | roster names are in the served HTML (checked on 258901) |
| free agents and waivers with clear dates, percent rostered and its change | the public players page `/nba/<id>/players?status=A&pos=P&stat1=R_O&sort=R_PO&sdir=1&count=<offset>` | checked in #92 on 258901: the rows are server-rendered, 25 a page; the Research view `R_O` carries roster status with the waiver date, percent rostered and started with the day's change, and Yahoo-wide adds, drops and trades. The same public page serves the stat views too, so a public league needs no sign-in for them: `S_PS7` and `S_PS14` (Yahoo's projections for the next 7 and 14 days), `S_PSR` (the remaining games), `S_L7`, `S_L14`, `S_L30` (last 7, 14 and 30 days, totals and averages) and the standard deviations (`S_SDL14` and the like) |
| the league's own adds and drops | the public `/nba/<id>/transactions` page | each move with its team, its time (`Oct 20, 3:57 am`, printed without a zone and read in US Eastern) and Yahoo's words for it (`$5 Waiver`, `Free Agent`, `To Waivers`); an add and the drop that came with it share a row group. Read on every public refresh; the private league's page is listed by the weekly recorder until read that day (#125, see "Decision log") |
| Yahoo-wide adds, drops and trades per player | the public buzz index `/nba/buzzindex` | the "surge in adds" signal for the breakout flag |
| this week's and next week's per-game projections with games, back-to-backs, minutes, injury, Yahoo ownership | Basketball Monster weekly export (imported with `scripts/draft_day.py week --this \| --next`, or `sources/bbm/fetch.py::weekly`, `this_week=True` for the rest of this week; `parse.py` already normalises it: `games`, `quality_games`, `back_to_backs`, `minutes`, `yahoo_owned_pct`, `bbm_adv_pct`, `injury`) | exported from the user's signed-in Chrome as the season export is, never with typed credentials |
| rest-of-season per-game projections | Basketball Monster season export, per-game | refreshed daily in season |
| recent production (minutes and rates over the last 7 or 14 days) | Basketball Monster past-days rankings (`fetch.py::rankings_past_days`) | the "minutes trend" signal |
| final box scores, every player's line in every game | ESPN's public scoreboard JSON for the date, then each final game's summary (`site.api.espn.com/.../nba/summary?event=<id>`, about 0.5 MB, its `boxscore.players` and `injuries`) | read on refresh for the Monday scorecard's realized values (#126): a date cached under `data/boxscores/` once every game on it is over, never read again; about 15 to 60 KB a date kept |
| NBA schedule by team and date | ESPN's public scoreboard JSON (`site.api.espn.com/.../nba/scoreboard?dates=YYYYMMDD`), one call per date, cached under `data/schedule/` | NBA's own cdn file answers 403. Read to the season's end for the Season view (#116): a date within the Moves card's four weeks is read again after 12 hours, a later one after a week |
| signed-in extras for every league (the user's Chrome, read-only): Yahoo's own projections per player for the next 7 and 14 days and the remaining games, last 7, 14 and 30 day totals, averages and standard deviations, percent rostered, roster status with the availability date, player notes; the home page's live matchup scores for every league | the players page and the home page in the user's signed-in Chrome, read with Claude in Chrome or the extension | checked 2026-10-21 on league 31822; a second weekly projection system for the blend the draft edge audit recommends, and the recent-production signal for the breakout flag. For a public league the players page serves the same views without a sign-in (row above); only the private league and the home page need the user's Chrome |
| news | ESPN injuries and Rotowire headlines (`scripts/draft_prep/news.py`, already built) | teammate injuries are the "opportunity" signal |

The home league 31822 is private: the same pages are read through the extension in the user's
signed-in Chrome (a content script on the team, players and matchup pages posting a snapshot to
the API), exactly as the draft room was read. Nothing in this module handles credentials; the
API path replaces the page readers the day Yahoo binds the app.

## The weekly projection, as built (#93)

`season/weekly.py` (core, no I/O) computes it and `api/season_week.py` loads its inputs; the
season view's payload carries it as `week_projection`, and the web multiplies per-game rates by
games.

- **Weeks.** The current matchup week and the next three. The current week counts from today,
  or from tomorrow once the matchup page was read at or after 19:00 ET, when the day's games
  are already in the week so far.
- **Games.** The game days of the player's NBA team in the ESPN schedule cache, then the out
  rule: INJ, OFS, SUSP and NA play no games in any week; O misses the rest of this week, and so
  does a GTD whom Yahoo's projection gives no games; D, Q and P keep their games. The row shows
  the status. A Basketball Monster weekly export that covers the week overrides the rule with
  its games column, and the player plays the last n game days of the week. The exports are
  `bbm_week_this_*` (the rest of this week) and `bbm_week_next_*`, each with a `.json` sidecar
  (`start`, `end`) that `scripts/draft_day.py week --this | --next` writes when it imports the
  browser's download (#117), as `sources/bbm/fetch.py` does for its own; a this-week export
  without one counts only on the day it was made. An export counts only when its sidecar's
  dates are exactly the week's first day and last day. So a morning export of the rest of this
  week is not counted once the matchup page was read at or after 19:00 ET that day: the week
  then projects from tomorrow, while the export's games include today's, and the schedule rule
  gives the games until the next morning's export. A matchup week that does not end on the
  coming Sunday needs the export's calendars set to it and the same dates given with `--start`
  and `--end`.
- **Starters.** Each day the players with a game fill the startable slots (the roster less BN,
  IL, IL+ and NA), best first by the chosen system's per-game value (a z-sum over the league's
  categories, or fantasy points). Augmenting paths let a starter move to another slot to make
  room, so the assignment is exact. `weekly.starters` takes any value vector, for #94.
- **Totals.** Per-game rate times games started, summed; FG% and FT% from makes and attempts.
- **Two systems.** Basketball Monster, the default: the newest rest-of-season export, per game
  as totals over games, matched to Yahoo ids. Yahoo: the players page's Next 7 Days (proj) view
  (`S_PS7`), its seven-day totals over its GP. The public refresh reads that view after the
  ownership view. The private league gets it when the user opens that view in Chrome, or when
  they arm a read from the side panel, which walks both views (extension 0.5.1). The Waivers
  table shows one system's nine totals, and hovering a total shows the other's.
- **The blend** (#152, `system=blend`). For a player Yahoo projects, each per-game rate is
  (1 − w) × Basketball Monster's + w × Yahoo's, w the knob file's `blend` (Yahoo's share, 0.5
  when the file names the blend system and no weight); everyone else keeps Basketball Monster's
  line, and a player only Yahoo projects keeps Yahoo's. A per-game value is the same mix of the
  two systems' own. The routes take `blend` as a system name; the dashboard's select still offers
  the two systems.
- **The system in force** (#152). A route that names no system solves on the one the knob file
  (`data/autopilot/knobs.json`, docs/AUTOPILOT.md section 6) has in force for the league,
  Basketball Monster's without one; a named system wins. The dashboard always names one, so the
  file's system reaches the routines' solves (the digest's moves and lineups) and not the panel.
  The decision log records it on each entry (`knobs.file_system`), and the scorecard projects a
  week on the system in force when the week began ("Scorecard", below).
- **Spread.** A counting category's weekly variance is φ_c times its weekly total. A percentage's
  variance sums, over started games, the binomial variance of makes on the attempts plus the
  attempts' own variance times (p − p_team)², taken over the team's total attempts. A points
  league uses Σ w_s² φ_s total_s. φ was fitted on ESPN's public 2025-26 game logs: 245 players
  with 30+ games and 20+ minutes a game, 15,767 games, fitted 2026-10-21, script in the scratch
  repository at `emissary/phi-2026-10-21`. The fitted values are PTS 3.17, 3PM 1.18, REB 1.34,
  AST 1.27, STL 1.07, BLK 1.12, TO 1.03, FGA 1.49 and FTA 2.24. Makes given attempts are
  binomial: FG 0.91, floored at 1, and FT 1.01. #97's recorder re-fits them from the leagues'
  own weeks.
- **Odds.** Each category's final adds the matchup page's week so far to the rest of the week.
  P(win) = Φ(Δ / √(σ₁² + σ₂²)), reversed for turnovers. Expected categories won is the sum of
  the nine. The opponent is projected for the current week only.
- **Matchup odds** (#116). The odds of winning the matchup take the categories as independent:
  the number of categories won is a Poisson binomial over the nine odds, and the matchup is won
  with more categories won than lost, a tie on categories counting half. Points and threes, or
  rebounds and blocks, move together, so this is a headline for the Matchup view; expected
  categories stays the measure the moves, the strategy and the standings use. A points league's
  one category is its own odds.

## The move model

A move is (add, drop), (add, nobody) when a slot is open, or (add, X to IL) when an injured
player can move into an open IL or IL+ slot, subject to the weekly add limit. Candidates are the
free agents available by the day the claim would process (a free agent now, a waiver player on
his clear date). A drop paired with a waiver claim takes effect when the claim clears, as
Yahoo's conditional drop does, so the dropped player keeps his games until then; a drop paired
with a free-agent add, and a free IL move, take effect on the first day. A move counts against
the add limit of the week in which it takes effect.

An IL move defers a drop; it does not avoid it (#97). The player moved comes back on the first
day of the first week the out rule lets him play: next Monday for an O, or ESPN's return date
when that is later, and he is held out until then. An INJ, OFS, SUSP or NA player stays out of
every horizon and costs nothing. On the day he comes back, the set drops its least valuable
active player by per-game value, the returning player included, and the drawer names that drop
("From Nov 4, X goes when Y returns"). This uses the starters' own ranking; it does not re-value
every choice.

Solver (resolved 2026-10-21 by fantasyMASTER on fantasyEMISSARY's prototypes): exact search on
the #93 evaluator, not an LP. This spec first called for one LP per horizon as on the draft
board. The prototype on a prize league (13 rostered, 213 priced candidates) showed why not. The
MILP with slot-level starts, a no-benching constraint and the draft's piecewise Φ took about a
second for the rest of this week and found the exact best swap there, but on the three-week
horizon with 27 category curves it hit the 30 s limit at every k, and its k = 2 answer was worse
than its own k = 1. Summing the three weeks into nine curves brought it to 3.5–7 s per solve with
its objective about 0.05 categories low from the piecewise Φ, and the deviation prices would
have needed 2k further solves per horizon. Exact evaluation of every (add, drop) pair with
`project_week` and the odds takes 0.4 s for this week and 2.2 s for three weeks, and greedy
exact swaps found a better set than the MILP in 0.8 s in total. So:

- k = 1 is exhaustive over every candidate and every drop: exact and global, it feeds the gain
  columns and the drawer's alternative drops and adds with their prices.
- The recommended set under the add limit is greedy exact swaps (the best swap, then the best
  swap given it) followed by a replacement pass that tries every alternative for each chosen add
  and drop until nothing improves; it stops early when the next add does not pay. It is a strong
  heuristic, not a proof, so the UI says "recommended", never "optimal", and a test checks it
  against brute force on a small league where k = 2 can be enumerated.
- The deviation price of an alternative is the same search re-run with that choice forced, so
  the card can say "dropping X instead costs 0.3 categories over the next three weeks".
- Every number agrees with the Matchup card because it is the same evaluator.

Solver, revisited for the strategy engine (#110, fantasyMASTER's ruling of 2026-10-21): the
linear program is exact and fast for this week, and on the season side the exact search finds
the better set more often, which is why both run there. The Strategy card shows whichever set is
better on its weight's exact value, with its source (see "The strategy engine" below); the
Moves card keeps the search alone.

Horizons: "this week" is the rest of the current week against the named opponent, with the week
so far; "three weeks" is weeks 2–4 (the Waivers table's G 3wk span) against the field, the mean
over the eleven other teams of the per-opponent category odds on their projected rosters (the
mean of the odds, not the odds against an averaged roster), since the state holds only this
week's matchups. Every move shows both gains whichever horizon chose it, so a streaming drop's
long-term cost is visible: the solver prefers the free agent with four games to the better
player with two, which is right for that week and wrong for the next, and the user chooses.

IL: an active player whose status the slot accepts moves into an open IL, IL+ or NA slot for
free, which opens a spot without a drop; players already in a held slot whose status still fits
it stay put and are not drop candidates. Which statuses fit which slot, how many held slots the
league has, and a held player whose status cleared are in "Held slots" below.

### Held slots (#107, #124)

Yahoo's rule for basketball (help article SLN6863, also served as SLN28136, read 2026-10-22):
an IL slot takes a player listed O or OFS; P, Q and D are not eligible. A player in a held slot
whose real-life status no longer fits it blocks every add and claim until he is moved to an
active spot, which needs an open one.

| slot | takes | source |
|---|---|---|
| IL | O, OFS | Yahoo's help pages: confirmed |
| IL+ | INJ, O, OFS, GTD | a 2021 Yahoo post only: unverified |
| NA | NA | unverified |

INJ is no longer taken for IL: the help pages leave it out. A status the model does not know
(anything but P, Q, D, O, OFS, INJ, GTD, SUSP and NA) is ineligible for every slot, and the
lineup route says so. The table is `season.moves.HELD_ACCEPTS`, with `HELD_CONFIRMED` naming
the rows a Yahoo page confirms.

How many held slots: the league's settings page, which lists every roster position. It is read
by the public refresh after v3's settings (part `league_settings`), and the extension posts it
for the private league. Until it is read, the held slots are a lower bound, the most of each
kind any roster read fills, and the lineup route says so (`held_lower_bound`). The draft-time roster
in the league folder is never used for them: it lists no IL, which kept the stash moves of #97
from ever firing in nine of the thirteen leagues. The settings page also gives the lineup rule
(v3's `weekly_deadline` is the fallback: `intraday` is daily from today), the playoff weeks
(used before the estimate, see the Season view) and whether an injured free agent may be added
straight to an injury slot (#124's no-drop add).

A held player whose status cleared (an IL player now listed Q, say) is the first thing the
Moves card and the lineup route say: he blocks every add. The model activates him on the first
day, dropping the weakest active player by per-game value, him included, in every set the
search weighs, the empty one too, so every gain is counted from that baseline. His slot then
counts as open for a stash.

Several players eligible for fewer open slots: the latest to return takes one first (a player
not back this season before any), roster order breaking ties (`moves.stash_order`). An add with
no drop and no open spot names the held move that makes room for him, "Brooks to IL", in the
Waivers table's For column, the Moves card and the Strategy card (`held` on each move). The
lineup route lists a player as eligible for every held kind the league has that his status fits,
a full one included, so the Lineup view can tell "eligible, IL full" from "eligible, 1 open" by
the slot's `open` count: when the IL is full the user decides whom to swap.

### The keep rule and the IL advice (#124)

The user's strategy rule of 2026-10-22, as ruled in docs/AUTOPILOT.md section 4. The three-week
horizon, and the season the Strategy card reads from it, value a player out for three weeks at
about nothing, so a good player out is a forced keep, not a value term (`season/moves.py`, "the
keep rule").

- **Values.** Each player's rest-of-season per-game value is Basketball Monster's line under the
  league's scorer, whatever system the solve runs on (Yahoo's are week projections). The pool's
  average is zero for a categories league's z-sums and, in a points league, the mean of the
  players the league rosters (its teams times their active spots, the best by value).
- **Protected**: all three of net positive (his value above the pool's average), not beaten by
  the best available add's value by the protection floor or more (his value plus the floor above
  the add's; the knob file's `protection_floor`, #152; `season_moves.PROTECTION_FLOOR`, zero,
  without one; a higher floor protects more, #164), and back this season. Out for the season, or INJ, SUSP or
  NA with no return date, is never protected; an O without a date is back next Monday.
- **Benched**: not beaten by the best add by the floor, not net positive, and back within seven
  days (`SHORT_ABSENCE_DAYS`). A replacement-level player out a few days is streamed like any
  other.
- **Forced keep.** Both are kept (`problem.kept`) on every horizon and every strategy weight,
  beside the user's locks: never a drop for the search (`drop_options`) or the program (no drop
  variable), and never the player a held player's return sends while another can go. The move
  drawer still lists them as drops, marked kept, to show what keeping them costs. A protected
  player out still goes to a held slot through the held move when one is open.
- **Value net of return**: his value above an empty line (a dead spot) times his games from his
  return to the season's last day, counted from the schedule on the days read and at the team's
  rate on the others (82 games in 174 days for a team with no day read). It ranks the IL and is
  shown for every protected player who is out; it never protects.
- **The advice** (`moves_payload`'s `stash`), for each of my players who is away (back after the
  first day, or not this season; a doubt who may play today is not): `stash` when he is
  protected and one of the league's held slots his status fits is open for him, with the best
  add for the spot it frees on each horizon; `il_full` when he is protected and eligible but the
  slots are taken, naming who should leave: a cleared occupant first, activated with the
  weakest active player dropped, else the occupant with the least value net of return, dropped
  and marked when the rule would protect him. That is advice only, no new move kind: the search
  never drops a held player. Then `bench` (protected with no slot for him, or the short absence)
  and `droppable` (the moves may take him).
- **The words.** The Waivers table says under its note whom the rule keeps and benches, and the
  Moves card lists them with their value a game against the best add's and why, then the out
  players' advice. A candidate with no move on either horizon carries the reason in words: "no
  adds left that week", or "no drop: every rostered player is protected or held", which the
  Moves card repeats.

Add limit: k is the league's weekly limit minus the adds already made this week, counted from
the transactions page; when that page does not reach back to the week's start the payload says
the count is unknown and uses the full limit.

Waiver claims (resolved 2026-10-21): the first version prices free agents and lists waiver
players with their clear dates without pricing the claim. Priority cost and FAAB bids come
later, keyed by the league's waiver setting.

### The rest of the season beside the horizons (#151)

Every move and trade the dashboard recommends or compares also carries its rest of the season
(the ROS column): from the move's day to the calendar's last day, playoffs included, the
decision log's own figure (`decisions.move_projection`'s season horizon, #144). That is the
add's games less the drop's, each times his per-game value under the league's scorer net of an
empty line, the games counted on the horizons' days and then from the schedule as far as read,
extrapolated past it at the team's rate. The tables, the log and the scorecard so value a move
alike. It is in value units (category z or points, over the games), not expected categories,
so it sits beside the two horizons and ranks nothing; the season guard (#164, below) draws one
line on it.

The payloads carry it as `ros`, `{value, add_games, drop_games, extrapolated: {add, drop},
from, to}`:

- on each candidate's `week` and `three` option, priced on that option's drop (the move the
  row's For column shows);
- on each recommended move, with the set's `ros` the sum of its moves';
- on the move drawer's move, its drops and its other adds;
- on the streaming plan's kept moves and steps, each valued as kept to the season's end, with
  `dropped_by` naming the later step that drops a streamer; the plan's total (`ros.plan`) sits
  beside the set's (`ros.set`), and the guard's refused plan carries its own against the set;
- on the stash's freed-spot add (#124). An activation from a held slot is no pool add and
  keeps the keep rule's `net`.

A trade's sides carry `ros: {before, after, change, from, unvalued}`, and each moved player
and the fill carry `ros: {value, per_game, games, extrapolated}`. These use the moves' problem
and scorer and each player's games to the season's end as a move's are counted
(`decisions.season_games`). The fill is valued beside the trade, as on the horizons.

### The season guard (#164)

The season is what counts: a set that wins its week can still cost the season. The season
guard holds every recommended set to a rest of the season of zero or more: the sum the ROS
column shows, each move valued on its own from its day as the log values it
(`moves.season_guard`, the master's ruling on #164, 2026-10-23).

- **The line.** A set is allowed when its moves' rest of the season sums to zero or more;
  exactly zero is allowed. A move without a season figure (an add or a drop with no Basketball
  Monster line) counts as zero, so it neither blocks the set nor pays for the rest of it, and the
  total is marked partial. Nothing inside the allowed sets ranks on it. Without the league's
  scorer or a season end there is nothing to guard on, and the payload says so (`season_guard`
  null).
- **Where it holds.** The search tries every set beside the add limit's test and the guard's
  (`moves.admitted`), and so do the re-solves that price each move, so a re-solve never offers a
  set the guard refuses. The streaming plan keeps each spot's path to the guard with the plan
  around it (the base, the earlier spots' steps and the later spots' own moves); its base is the
  guarded set's, so it starts on the line. The strategy engine guards every weight's search and
  re-solves, and takes the linear program's set only when the guard allows it, else the
  search's stands (both options, A and B). The private league is guarded the same way: it is the
  same engine, and the user still makes every move there by hand.
- **What it held back.** On each horizon the engine solves once more without the guard,
  re-solves and all (a re-solve can find the costly set a plain search misses; only when the
  guard refused a set, since otherwise the solve was the unguarded one). When that set beats the guarded one on the horizon and its rest of the season is below
  zero, the horizon's `season_guard` names it: `{held_back: true, moves, gain, ros: {value,
  partial}, forgone, saved}`, each move with what it adds to the set, its rest of the season and
  the log's `season_costly` flag, then what the guarded set forgoes on each horizon and saves
  over the season. Otherwise `season_guard` is `{held_back: false}`. A strategy weight's names
  the better on the weighted value of its unguarded search's set (re-solved the same way) and a
  refused program set, with `program` when it was the program's.
- **The Moves card.** Under a set the guard changed, one muted line: "The season guard held back
  a set that gains +1.50 on the week but costs the season −95.0; this one forgoes 1.15." A
  partial total says so. The held set's moves are in its tooltip, flagged season-costly, never
  shown as recommended. The landing grid's best move reads the guarded set, as it reads
  `recommended`. The Strategy card says when the guard held back the program's set.
- **The plan.** When the season guard, not the three-week guard, is what keeps the best-week
  plan out, its `reason` is `season` and `guard` gives the refused plan as for the three-week
  guard ("... but costs the season −12.4; the season guard holds it back.").
- **The log.** Each logged set carries `season_guard`: whether a set was held back and, when one
  was, its moves (add, drop, day, gain, rest of the season), its gain and its rest of the
  season, so the scorecard can tell a move the guard held back from one the user chose.

The keep rule and the season check stay as they are: the keep rule protects the players worth
more than the best add, and the check counts the moves flagged season-costly. The guard is what
keeps a set below the line from being recommended at all.

## The strategy engine (#110)

The Moves card answers one horizon at a time. The Strategy card weighs this week against the rest
of the season on one value, for a weight λ:

    λ · (expected categories this week) + (1 − λ) · (weeks left) · (a later week's)

where a later week is the three weeks ahead averaged: "rest of season, from the three weeks
ahead", the three-week horizon taken as the stationary later week, times the calendar's weeks
after this one. Since #151 it is labelled "season pace", so it is never read as the
schedule-based rest of the season the ROS column shows. Four weights make the frontier: this week alone (λ = 1); this week as much as all
the rest together (λ = w / (1 + w) for w weeks left); every week alike, the natural weight (λ = ½,
the season's own total halved); and the rest of the season alone (λ = 0). With no week after
this one there is only this week's. A points league counts matchups where a categories league
counts categories. Every value is the move model's evaluator, so the card agrees with the Moves
and Matchup cards.

The pool is the 30 candidates whose best single swap gains most, the two horizons' rankings
interleaved so the best on either is in; `pool` (up to 60) is a query parameter. Two solvers
answer each weight (option A, provisional until the user rules):

- **The exact search**: the move model's search (greedy exact swaps and the replacement pass) on
  the weighted value, its set then priced by re-solves as on the Moves card. Its sets are the
  first answer, about two seconds once the moves are valued.
- **The linear program**: the draft's roster MILP applied to the moves, HiGHS through PuLP.
  Binaries add a candidate and drop one of my players on one of the days an add arrives (the
  first day for a free agent, the clear date for a claim), each at most once and on each date no
  more drops than adds; a drop keeps his games before his date, and each week's adds stay within
  its limit. This week's starts are a matching of players to slots on each day; a later week's
  are capped by count at the number of starting slots. Each category's total goes through the
  draft's piecewise Φ: this week against the named opponent's final, a later week against the
  field (the other teams' projected weeks from every game their rosters play: the mean, and the
  spread between teams plus two teams' weekly noise). It starts from the search's set, runs for
  at most 10 s to a 10⁻⁴ gap, and HiGHS's own status says whether it solved, stopped at the time
  limit with a set, or found none. Since #124 it makes the held-slot moves too: a binary per
  eligible active player and open held kind, no more than that kind's open slots, never with a
  drop of his before his return. A stashed player's return day is one of the dates a drop may
  fall on, and on every date the adds arrived less the drops and the stashed players not yet
  back stay within the spots open now. The keep rule's players have no drop variable. Its set
  goes back through the evaluator, which picks the stashed players and charges the returns its
  own way, and the search's held moves and returns seed it.

The card recommends whichever set is better on the weight's exact value, and says which: the
search's, the program's, or both when they found the same adds with the same drops on the same
days. A program's set that a re-solve beats while it is priced becomes the search's answer, with
a note. Option B is one switch, `program_only`: the program's set whenever it solves to the gap,
the search's only when the program hits its limit or finds no set; the default stays on A. Under
either option the season guard (#164) holds the search and its re-solves, and a program's set
it refuses is never taken.

The field curve uses every game of the other teams' rosters rather than their projected starts.
The program's count cap ignores positions, so it overstates my own starts by the same token; on
the prize leagues' data an isolated check found the starts curve equal or worse at every point.

At the program's solution each player also gets a first-order value: the curves' slopes there
times his line over every game he plays, weighted as the program weighs the horizons. The card
lists the pool's highest outside the set and my lowest not dropped, as a ranking of whom to look
at next, not a price (the prices are the re-solves'). A player of mine whom the keep rule keeps
is marked "kept" there: low as he may rank, no move drops him (#124).

`GET /seasons/{id}/strategy?system=` returns today's run for the snapshot as far as it got and
never solves; `POST` with `pool`, `weights`, `lock` (my players never dropped, repeated) and
`program_only` starts one, replacing an older run of that league and system (`wait=true` blocks
until it finishes, for tests). A run searches every weight, then solves the programs in a
background process pool while the searches' sets are priced, then chooses. The card is the rail's
seventh: it opens on the recommended weight (the knob file's `horizon_weight`, #152, the natural
weight by default; its tab says "recommended", and nothing executes it) with a Solve button and
solves nothing on load; the
frontier plots each weight's set by its gain this week across and over the rest of the season
up, hollow the search's, solid the program's, half both, the natural weight ringed; a weight's
tab shows the set with a lock on each drop, the categories before and after, the first-order
lists and the solvers' seconds and sizes. Like every card it says "recommended", never
"optimal", and nothing in it acts in Yahoo.

## Lineups (#107)

`season/lineup.py` (core, no I/O) and `api/season_lineup.py`;
`GET /seasons/{league}/lineup?week=N&system=bbm|yahoo`, the current week when `week` is left
out, any of the Moves card's four weeks.

- **Recommended.** Each day, the players who play (the move model's schedule, out rule, games
  and returns, `weekly.playing_days`) placed by `weekly.starters`, the same daily starters the
  projection counts. The sets a lineup's slots can hold form a matroid, so the most valuable
  set is also the one that starts the most games: no legal lineup starts more. A league whose
  lineups change weekly gets one lineup for the week, each player worth his games times his
  per-game value. Held slots never start.
- **First day.** A day before the first day a change counts (the move model's first day, or
  tomorrow in a league whose changes count from tomorrow) shows Yahoo's lineup only.
- **Yahoo's lineup.** My team page shown for the day (`lineup/<team>/<day>`), or for today the
  team page read today. A public refresh reads today and the days after it every time, and
  each day before today of this week or the last until it was read after the day (#149): a
  lineup read on its own day may change later that day. Lineup parts older than fourteen days
  are dropped when the season is saved. The private league's pages come from the user's Chrome
  (extension 0.5.3): the route's `needs` lists the settings page until read and each day ahead
  not read today, and the weekly recorder's response lists them as `lineup_pages`, after the
  schedule pages, with each day of the week recorded not read after it.
- **Comparison.** Per day, the players each lineup starts who play that day; the games lost are
  the recommended count less Yahoo's, and `start` and `sit` name the difference. Two lineups that
  start the same players in other slots are no difference.
- **Games lost (#149).** The weekly record counts my player-games lost to the lineup as set:
  per day, the most of my starters and benched players who played that the starting slots can
  hold, less my starters who played (`season.lineup.lost_games`). That is the issue's rule made
  exact, and it supersedes the issue's one-by-one wording: a benched player who played counts
  when a slot he fits was open or held a player without a game, or could be freed by moving its
  starter to one, and two benched players who could take only one such slot count once. Held
  slots neither start nor count. Who played is the box-score cache's (#126): a line that is not
  empty. A day counts only with its lineup read after the day and its box scores cached; any
  other day is not read and adds nothing. The record's `lineup` is `{lost, days_read, days,
  unmatched}` (`lost` None when no day was read; `unmatched` the players of a read day's
  starting slots or bench whom no box score of the week matched), kept until a record that read
  more of its days. The scorecard's card carries it, the Progress view's league table shows it
  with the days read, and the Monday markdown sums it over the public leagues.
- **Payload.** For an executor to consume later, every recommended day is slot by slot in the
  league's slot order with Yahoo player ids (`recommended: [{slot, player}]`, the bench beside
  it), and Yahoo's as read the same way with when and from which page it was read. Then the held
  slots one by one with their occupants (cleared ones marked), the open ones and the active
  players eligible for one; the rule and its source; the alerts in order (a cleared occupant
  first, then an unknown status, the held lower bound, an unknown rule); a summary (games lost,
  the days that differ, the days not read); and the players named. Each day also lists my
  players who play that day (`playing`), for the view's bench row, and `weeks` the weeks the
  route answers. Nothing here applies a lineup.
- **View.** The dashboard's Lineup view (`l`, "In the dashboard") shows the payload: a grid of
  slots by days with the differences lit, the games lost per day, and the held slots.
- **Digest.** `GET /flags/digest`'s markdown carries a Lineups section. First comes a line
  per league whose held slot holds a player whose status cleared: he blocks every add until
  activated, and the activation's drop is named. Then comes one line per league whose lineup as
  set loses a game today or tomorrow, with the players to start and to sit and the games lost.
  Both use names only, and the section is left out when there is neither. The daily routine
  posts the field as it is.
- **Script.** `scripts/season.py lineup [league ...] --all [--days 2] [--json]` prints the same
  line per league for the terminal.

### The executor's steps (#170)

`season/lineup.py`'s `target_lineup`, `lineup_steps` and `apply_steps` (core, no I/O), served by
`GET /seasons/{league}/lineup/steps?date=` (`api/season_autopilot.py`; the guardrails are in
docs/AUTOPILOT.md section 2).

- **Target.** The starters are Yahoo's as read, less the comparison's `sit`, plus its `start`:
  the recommended set, never re-solved. They are placed in the league's starting slots so the
  most of them stay where Yahoo has them (an exact search over the slots), everyone else goes
  to the bench, and a held slot's player stays where he is. None when the set does not fit the
  slots as read.
- **Steps.** From Yahoo's lineup to the target one move at a time, each legal on its own: a
  player into an open starting slot first, then a bench player into his slot with its occupant
  to the bench, then a starter into another starting slot when the occupant can take his, then
  a move to the bench. The bench takes anyone (Yahoo lets it run over its count while a starting
  slot is empty), and a player moves at most once to his slot. Steps that share a slot or a
  player form a group; groups share neither, so a group can be dropped without breaking another.
- **Payload.** The day, the team page, the mode and STOP; whether the day still takes changes
  and why not; the read the steps came from; the steps with the player swapped, his tip-off and
  his group; the groups left out because a game began; each moved player's final slot; and the
  games each lineup starts (recommended, Yahoo's, after the steps). Tips come from the schedule
  copy of the day (ESPN's event times, kept beside the teams since #170); a day copied before
  that has none, which a dry run allows and live will refuse. For the page's own check the
  payload also carries the league's starting slots (`slots`) and each player's slot as read
  (`yahoo`): the extension runs only against the lineup the steps were built from.

### The moves executor's queue (#171)

`season/autopilot.py` (core, no I/O: the entries, the floor, the bid, the veto window) and
`api/season_queue.py` (the store and what a build reads); the routes and the guardrails are in
docs/AUTOPILOT.md section 2, the bid in section 5.

- **Reads, never a solve.** A build reads each armed league's last moves entry of the day in the
  decision log, its three weeks' set and knobs; the keep rule's protected players from the
  engine's build of the day (`Built.rule`, the same rule the solve ran under); the breakout
  flags; each available player's `FA` or `W` and clear date; my team's FAAB budget; my drops
  within the waiver days from the transactions page; the adds left per week from the entry's
  `adds`, less the claims placed and not processed.
- **The scored floor's spread** pools the public leagues' scorecard rows of group `scored` whose
  judging horizon is complete (`season_scorecard.compared_move`, the rows the Monday summary
  compares), by scoring, and never the private league.
- **The typical gain** is the median of the armed leagues' three weeks' moves over the last 14
  days (each day's last moves entry), by scoring.
- **The dry-run pass (PR 2, extension 0.7.0).** The routine opens each due entry's add page with
  `#pickandroll-moves` (and later `#pickandroll-moves-late`); the extension checks that entry on
  the rendered claim form and logs the claim it would place, submitting nothing (AUTOPILOT
  section 2, "The page check"). The due route gives it my team, each entry's page, the claims
  still pending, the day's entries executed and the adds left less every claim since. A dry
  run moves no queue outcome: the pass is in the log and the digest, and the entry stays due.

## Decision log (#125)

`season/decisions.py` (core, no I/O) and `api/season_decisions.py`;
`GET /seasons/{league}/decisions?from=YYYY-MM-DD&to=YYYY-MM-DD`, the last seven days to today
when left out.

- **Entries.** Each solve of the moves route (once per day and inputs: a cached answer writes
  nothing) and each strategy run that solved appends one entry to
  `data/leagues/<id>/season/decisions/<date>.json`, the date in US Eastern, for every system
  solved. An entry holds its time, the route, the projection system with its export file, the
  knobs the solve ran with (`knobs`, #152: every knob of docs/AUTOPILOT.md section 6, the
  league's from the knob file over the code's defaults, with the system the solve ran on: the
  system and the blend weight, the horizon weight the strategy marks recommended, the keep rule's
  protection floor, #124, the streaming plan's floors, #136, and its moves a day, and the stash
  threshold and the FAAB sizing, recorded though nothing reads them; beside them `file_system`,
  the system the knob file had in force for the league, which a route naming another overrode;
  a strategy entry also names its `recommended` weight and marks that weight's set), the first day a
  move counts, the adds left, the horizons' labels and the pool (the moves route's search pool,
  candidates and floor; the strategy's players and settings). Then one set per horizon (moves)
  or per weight (strategy):
  its moves (add, drop or nobody, the day it counts from, and the bid to make, null until the
  FAAB sizing of phase 2), the held slots it uses and the comebacks it implies (moves), the
  weight and where the set came from (strategy), its gains, and this week against the named
  opponent before and after it: each category's finals and odds, the expected categories won
  and the odds of winning the matchup. A recommended streaming plan (#136) is one more set of
  the moves route's, `plan`, its moves counting from their days. Since #164 each set also
  carries the season guard's record, `season_guard` ("The season guard"). A strategy run cut
  off before it solved logs nothing. A failure to write loses that entry, never the answer.
- **Moves in value units (#126).** From 2026-10-22 an entry also keeps its `scorer`: the
  league's, the keep rule's (Basketball Monster's lines over the players the league rosters),
  as data (`weekly.scorer_of`: a points league's weights, or each category's spread and, for
  a percentage, the pool's rate its impact column weighs a line's attempts by, unrounded), so
  the scorecard values the actual lines exactly as the solve valued the projections, without
  rebuilding the scorer from an export that may be gone (master's ruling, 2026-10-22). Each
  recommended move keeps its own `gain` on each horizon as
  the solve priced it (the set with it against the set without it; null for a strategy move
  left unpriced) and its `value`: the add's and the drop's per-game value under the scorer net
  of an empty line, and on each horizon its first and last days, the games each was assumed to
  play there (the add's from the day the move counts, the drop's given up from that day or from
  his return when later) and the move's value, the add's games' less the drop's. An entry
  logged before them projects no move in value units, and the scorecard values the moves
  matched to it with the scorer of the entry nearest them ("Scorecard", realized value). From
  2026-10-23 each horizon of a move's value also splits it by category (`cats`: a categories
  league's categories, a points league's scoring stats, summing to the value; #129).
- **My moves.** My team's rows on the transactions page, one per row group: an add with the
  drop that came with it, a lone add or a lone drop, with its time and the bid as read (`bid`,
  dollars, from Yahoo's `$5 Waiver`; null for a free agent's add). A trade is not a move here.
  The page prints its times without a zone, in the zone of the Yahoo account that opened it;
  they are read in US Eastern (`season_decisions.TRANSACTIONS_TZ`), an assumption, since the
  user's Mac runs on US Central.
- **Match.** Each move against the latest entry logged before it, over every set of that entry:
  `as_recommended` (a set holds the same add with the same drop, nobody being an open spot or a
  held slot), `differently` (a set adds the same player for another drop or drops the same
  player for another add), `not_recommended` (no set names either player) or `no_entry`
  (nothing logged before it). The entry may be older than the range shown. A move with an
  entry within an hour of it, before or after, is flagged `near`: a wrong zone could have
  matched it to another entry, so its kind is checked before it is scored.
- **Payload.** The entries in the range, oldest first; my moves in it, each with its match and
  the entry it was matched to; the count per kind and of the near ones; when the transactions
  page was read; and the names of the players in both. The private league answers the same from
  its posted page. The Monday scorecard (#126) reads it.
- **Pages.** A public league's refresh reads its transactions page. The private league's is the
  user's Chrome's: the weekly recorder's response lists it as `transactions_page` until a page
  read that day is posted, and `scripts/season.py record` prints it after the lineup pages.
- **Script.** `scripts/season.py decisions <league ...> [--from] [--to] [--json]` prints each
  solve with its sets, then each move with its match ("near a solve" when flagged), one per
  line, times in US Eastern.
- **Routine.** An entry is written only when something solves: the Moves card, the landing
  grid's solve button and the Strategy panel's run. The digest solves nothing, so for an entry
  every day the daily routine asks `GET /seasons/{id}/moves` of each league after its refresh
  (docs/AUTOPILOT.md, the daily row).

## Scorecard (#126)

`season/scorecard.py` (core, no I/O) and `api/season_scorecard.py`;
`GET /seasons/{league}/scorecard?week=N&system=bbm` and `GET /seasons/scorecard?week=N`, the
last recorded week when left out, each week on the system in force when it began when `system`
is left out (#152). The metric is docs/AUTOPILOT.md's, section 6.

- **The projection.** A week's is the decision log's last entry on the system scored whose
  first day is the week's first: a solve that saw the whole week, before its first game (once a
  day's games begin, a solve's first day is the next). Its week block before any move gives each
  category's finals and odds, the expected categories won and the odds of winning the matchup.
  A week without one is unprojected: shown, but in no sum. Week 1 is unprojected (the log began
  on Oct 22). With no system named (#152), the system scored is the one in force when the week
  began: the `file_system` its first week-start entry recorded (`bbm` for an entry logged before
  entries kept it). The projection is then the last week-start entry with that `file_system` that
  was solved on it, so a change of system made on the week's Monday leaves the week on the old
  system for both halves. A named `system` wins. A move with no scorer of its own borrows the
  nearest entry's solved on the system in force when it was logged.
- **The result.** The weekly record's (#97): my categories won, lost and tied (a points
  league's points), the outcome, and each category's totals, a percentage from its makes and
  attempts to Yahoo's three decimals, the lower turnovers winning; my rank and record after it.
- **My moves.** The week's transactions as the record keeps them (`transactions`: every
  transactions page read from the day before the week to a week after it, a row group once
  however many pages listed it; the page lists only the latest few dozen), or for a week
  recorded before the record kept them, the season's page. Each is matched to the entry before
  it as the decision log matches (`as_recommended`, `differently`, `not_recommended`,
  `no_entry`, `near`); a move made as recommended carries the entry's `gain` and `value` for it.
- **Pooled.** Over the public leagues that projected the week: the matchup odds' Brier score
  (a tie half a win) and the category odds in five buckets of 20 points, each with its count,
  its mean odds and its share won; a points league's one category is its matchup, in the Brier
  score only. The leagues that did not project it and those not recorded are named; the
  season to date pools every projected week the same way. The private league is shown apart
  and never pooled: its moves are suggestions only.
- **Season to date.** Per league: the record, the projected weeks' expected wins (the matchup
  odds summed) against the wins (a tie half), the expected categories against those won, the
  standing after the last week, and the moves by match with the logged projections' value
  summed on each horizon.
- **Realized value (part 2).** `season/realized.py` (core, no I/O) and
  `sources/boxscores.py`. Each move's added player's games in its span less the dropped
  player's, both from the move's time on (a game that began before it is neither's), each
  game's actual line valued with the entry's scorer (`weekly.net_value`, the units the entry
  priced the move in), every game the two played counting whoever started. The spans are the
  projection's horizons from the move: `week`, from its day to its week's end, and `three`, the
  three matchup weeks after it (master's ruling, 2026-10-22). `lag_days` is the days from the
  matched entry's first day to the move's: a late execution's shortfall reads for what it is,
  and at zero the spans are the logged ones. A span counts through its last day read without a
  gap from its first (`through`, `complete`, and the days over but not read in `missing`). The
  scorer is the matched entry's; a move with no entry, or one matched to an entry logged before
  entries kept their scorer, borrows the scorer of the entry nearest it on the league's system
  scored (`scorer.own` false) and is realized only (ruled 2026-10-22). A later move that drops
  the added player counts his games from then on against itself, so a stream's moves add up to
  what the spot made. Each span also splits its value by category (`cats`, as the logged
  projection does; #129). A move made as recommended carries its set's odds of winning the matchup
  and its expected categories before and after the set (`projected.odds`), and every move the
  knobs in force at the entry it matched (`knobs`).
  - *Box scores.* A refresh (a public league's, and a private league's extras) caches every day
    of the season to yesterday not cached yet, oldest first, at most 14 a refresh: the date's
    scoreboard, then each final regular-season game's summary, every player's line (minutes,
    points, makes and attempts, threes, rebounds offensive and defensive, assists, steals,
    blocks, turnovers) and the injury report's players with no line. A date is written to
    `data/boxscores/<date>.json` only once every game on it is over or will not be played on
    it, and is never read again. The scorecard reads the cache only.
  - *Matching.* A Yahoo player's ESPN id once matched is kept (`data/boxscores/ids.json`);
    otherwise he is matched by name among his NBA team's players in the span's games, else by
    the name alone over every team (a trade inside the span), with the names normalised as the
    projections' are. A player matched by neither is a gap: his team's games in the span are
    counted in `gaps` and the span has no value, never a zero; until his team plays there is
    nothing to miss. On 2026-10-22 the rostered players of every league whose team had played
    matched 185 of 188, all on their own team; the three left were in neither the box score nor
    the injury report of their team's game.
  - *Groups.* A move has a realized value (`valued`) when its time is on the page, a scorer
    values it and its week's span has a day read and a value; else `reason` says why
    (`no_time`, `no_scorer`, `not_read`, `unmatched`). Each move is then in one `group`:
    `scored`, projected by its own entry (made as recommended) and realized under its scorer;
    `realized_only`, realized with no projection of its own or under a borrowed scorer; or
    `unscored`. The moves summary counts the three, sums the realized value of every move
    realized on each horizon through the days read, counts the spans complete, the unscored by
    reason and the gap games, and over the scored moves whose judging span is complete
    (`compared`, null for none) sums their projected and realized values, the realized share of
    the projected (none when the projected sum is not positive), how many realized in the
    projected direction (`same_way`) and how many were judged on each horizon (`horizons`).
  - *The judging horizon* (#143, ruled 2026-10-23). Every move is judged on the horizon its set
    was recommended for, written on its row as `judged`: the week's set and the streaming plan on
    the week, the three weeks' set on the three weeks after, the strategy's set under the week
    weight on the week and its others (the even and the natural weights) on the three weeks after,
    a move with no projection of its own on the week, and (#144) a strategy set solved under the
    season weight on the season once its projection has that horizon. `compared`, the sentences, the markdown
    and the Progress screen all count the same moves on the same horizon; a move keeps its
    values on every horizon beside it.
  - *The season horizon* (#144, ruled 2026-10-23). The season is what counts, so every move
    also carries a `season` horizon, shown beside its judging figure, never in its place. The
    decision log projects it from the move's day to the calendar's last day (the league's, the
    playoffs included, where the keep rule's `games_left` counts to). Its games are:
    - on the week's and the three weeks' days, those horizons' own counts;
    - after them, from the day the player is back as the keep rule reads it (none when he does
      not return this season), his team's games on each day the schedule was read, and on the
      others his team's games a day over the read days. Those last games are extrapolated, and
      `extrapolated_games` says how many, for the add and the drop. The rate is never the
      player's own three-week games, which are zero while he is out.

    The realized value has a `season` span over the same days, complete only once the season
    ends and "so far" until then. The summary sums it beside the others; its gaps are not
    counted, since it overlaps the other spans.
  - *The season check* (#144). At decision time the log flags a move `season_costly` when both
    hold:
    - its projected value on its judging horizon is above zero;
    - its season projection is below zero, whatever the keep rule's protection floor (#164:
      the floor only decides who is protected; the season guard draws the same line).

    A move logged before the flag has none. The row carries the flag. The summary counts the
    moves projected below zero over the season (`season_negative`) and the flagged
    (`season_costly`, of those `checked`), each with how many of the scored among them realized
    below zero so far (`below_so_far`). A sentence on the Progress screen says the same by unit.
    The check measures the keep rule; it changes nothing in the engine.
- **Markdown.** `markdown` in the all-leagues answer, for #127: leagues by id, no team or
  league names, no projected player line; the odds, results and standings as aggregates, a row
  per league, the private league in its own table, and my moves by the players' names and how
  they matched, then the moves realized, this week's and the season's to date, pooled over the
  public leagues and apart for the private one, in counts and ratios only: the scored with
  their realized share of the projected and how many went in the projected direction, each on
  its judging horizon, the realized only, the unscored by reason and the gap games, and once a
  move has a season projection, the moves projected below zero over the season and the flagged
  season-costly, each with how many of them realized below zero so far. No value in scorer units
  appears there, for a move or summed (master's ruling, 2026-10-22: docs/AUTOPILOT.md section
  8 keeps Basketball Monster numbers and what reduces to one out of the issue); the values stay
  in the JSON, the script's lines and the card. Since #149 a line sums the player-games lost to
  the lineup over the public leagues, with the league-days read of those recorded ("Lineup: N
  player-games lost over the public leagues (D of T league-days read)"), left out when no day
  was read.
- **Script.** `scripts/season.py scorecard [league ...] [--week N] [--json]`: the week's
  markdown, or one line per league named.
- **The card (part 3).** Card 8 on the league page's rail, Scorecard: the last recorded week
  by default, the arrows stepping through the others; its line (the matchup odds and expected
  categories projected, or "not projected", the result, the standing after it), then its moves,
  each with its day and how it matched under it, its projected value on its week, and its
  realized value on its week and on the three weeks after, in the scorer's units (a points
  league's to one decimal, a categories league's to two). A move realized only, or unscored,
  shows its values dimmed or a dash; a row's tooltip lists each span's games, how far it was
  read, its gaps and missing days, a borrowed scorer and the lag. Then the season to date: the
  record, the wins and categories against the projected weeks' expected, the Brier score, and
  the moves summary (the three groups, the realized sum, and the scored moves' realized sum
  against their projected, its share and how many went the projected way). In the private
  league the card says "suggestions only".

## Streaming plans (#136)

A marginal spot is worth more as a stream than as a seat (user, 2026-10-22). When an active
spot's occupant is below the waiver replacement level, turning the spot over several times in a
week buys more games, and more of the week's categories, than any single add, and costs nothing
on the three-week side because nobody worth keeping is lost. The Moves card's single moves
cannot say "add A now, drop A for B on Thursday"; the plan can.

- **The model.** A move gains a `day`, its effective day, at or after the candidate's earliest
  (the first day for a free agent, the clear date for a claim), and a drop may be an earlier add.
  A set of dated moves is a roster timeline: the evaluator derives each player's `available_from`
  and `gone` from it and values it with `project_week` as it values single moves, which keep
  their one day and are unchanged.
- **Stream spots.** The active spots whose occupant is below the waiver replacement level, the
  best available add by rest-of-season per-game value, and neither protected nor bench-kept by
  the keep rule. The weakest two at most (`STREAM_SPOTS`); the planner takes them one after the
  other, each with the earlier spots' plans made and the later spots' own moves from the set, so
  a spot never takes the adds the set gives another. The base is the week's set less its moves
  that drop a stream spot's occupant. Open spots are not streamed: the set fills them as before.
- **The plan.** For a spot, a path over the days left in the week: who holds the spot each day,
  under Yahoo's rules and the autopilot's: the week's adds left, one per step; a free agent
  available at once, a player I drop on waivers for the league's waiver period
  (`waiver_days`) and not re-addable inside it, a waiver player available from his clear date;
  a player whose game has begun locked until the next day; at most two executed moves per league
  per day (docs/AUTOPILOT.md, section 2); the step's add with a start slot that day under the
  lineup rules.
- **The search.** A dynamic programme over days (`season/stream.py`) with a cheap score per day
  and holder: his per-game value under the league scorer, net of an empty line, when he has a
  game that day and would start it beside the rest of the roster. A whole path also counts its
  last holder's games in the three weeks after at the same value. It keeps the best five partial
  paths per holder and adds used (`KEEP`); nobody holds a spot twice in a week, which is stricter
  than Yahoo's waiver period and keeps each player's timeline to one interval. The best eight
  whole paths (`EXACT`) are valued exactly with the Moves card's evaluator against the spot as
  the set leaves it (its own move for the spot, else the occupant kept), and the spot's plan is
  the one with the best week among those no worse on the three weeks after. The single-move set
  stays the baseline: a plan is recommended only when its exact week value beats the set's by
  more than the floor until the scorecard (#126) sets a noise floor: `PLAN_FLOOR_CATS`, 0.10
  expected categories, in a categories league, and in a points league, whose week is the
  matchup's win odds on [0, 1], the same share of the scale, `PLAN_FLOOR_POINTS`, 0.01. Both are
  knobs (docs/AUTOPILOT.md, section 6) the decision log records. It is a heuristic, so the card
  says "recommended", never "optimal", and a test checks it against brute force on a small league.
- **Horizons.** A plan lives inside the current week, and its final holder stays: the
  three-week horizon values him as it does any add. A plan never costs the three weeks after
  against the set (above), a hard rule for the autopilot, which cannot weigh a week's gain
  against a later cost the way the user can; its three-week change shows beside its week gain.
  When the plan with the best week would clear the floor but costs the weeks after, the payload
  says the guard refused it and gives its steps, games and gain on both horizons, so the user
  sees the trade and can make it by hand. The season guard (#164) holds the plan too: when it,
  not the three-week guard, keeps the best-week plan out, the reason is `season`.
- **Output.** The moves payload's `plan` beside `recommended` (null without a stream spot):
  `base`, the set's moves it keeps; `steps` by day, each a move (`add`, `drop`, `from`, its day)
  with the `spot` it turns over and its own gain on both horizons (`marginal`, the plan up to it
  less the plan before it, so the gains telescope); `spots`; my started `games` this week with no
  move, the set and the plan; the `held` slots and `comebacks` as a set has them; the `adds` of
  the set and the plan; the expected categories (`value`) with no move, the set and the plan on
  both horizons, and the plan's `gain` on the set; `recommended`, and `short`, how far its week
  falls short of the floor, and `reason`, why it is not recommended: `short`, under the floor,
  `guard`, or `season` (the season guard's refusal, #164), with `guard` the refused plan (its
  steps by day, the spots, my started games with it, its gain on the set on both horizons and
  its rest of the season less the set's). The Moves card shows a Streaming plan section
  under the week's set when it is recommended: the steps by day with each one's gain, then the started games and the
  adds against the set and the set's moves it keeps. A plan not recommended is one muted line
  instead, what it would have bought ("Streaming Grant's spot buys 2 more started games for +0.04
  this week, under the 0.10 floor."), or for the guard's refusal what it buys and costs
  ("... for +0.15 this week but costs 0.47 over three weeks; not recommended.", its steps in the
  line's tooltip). Every moves entry of the decision log (#125) carries the plan's verdict,
  `plan`, whatever it is: recommended or not and why, the plan's and the set's expected values
  on both horizons, the shortfall, the floor and the refused plan's gain and rest of the season
  when a guard refused one, so the scorecard can count the plans foregone and judge the floor; null without a stream
  spot. The log keeps a recommended plan's steps as one more set, `plan`: the kept moves, then
  the steps, each with its `from` and the #126 fields, the step's `value` counting the add's games and the drop's from the step's
  day (the drop may be an earlier step's add), so the steps' values sum to the plan's and the
  scorecard scores a stream like any move. `scripts/season.py decisions` prints the plan's moves
  by day. The executor (docs/AUTOPILOT.md, phase 2) takes the day's step only; the plan is
  re-solved every morning.
- **Out of scope.** FAAB bids on a stream's claims (section 5 of docs/AUTOPILOT.md applies
  unchanged), plans across weeks, the executor's clicks.

## The breakout flag

A pickup that might be a long-term asset deserves a sign on the card distinct from his
three-week number, because the number is built from projections that lag a role change by days.
The flag combines four signals, each shown with its evidence, and never adds anyone by itself:

1. **Adds surge.** Yahoo-wide adds in the last day from the buzz index, and the change in
   percent rostered on the players page, both against the player's own baseline (a player at
   2 percent rostered gaining 5 points is a louder signal than a star gaining 5).
2. **Minutes trend.** Minutes and usage over the last 7 and 14 days from the past-days export
   against his season per-game projection; a player playing eight more minutes than projected
   for two weeks is a role change.
3. **Value gap.** Basketball Monster's rest-of-season value against percent rostered: a player
   ranked inside the top 120 and rostered in under half of leagues is undervalued by the market.
4. **Opportunity.** A teammate at his position on the injury list with a multi-week note
   (from the news sweep), which is why the minutes moved.

Each signal is a score from 0 to 1 and the flag has three levels (watch, add, must-add) from
their sum, with the thresholds tuned on last season's buzz index history once two weeks of
data exist. The flag appears on the Moves card and on the free-agent list, and a daily digest
of flagged players across all leagues can go out as an alert (channel: see the open decisions).

As built (#95, PR #104, 2026-10-21). The flag is computed when read and cached like the moves;
a refresh stores the day's buzz index, keyed by the NBA day, and ESPN's injury report under
`data/leagues/_shared/season/`, and the past-days export is imported from the browser's download
with `draft_day.py past-days 7|14`. Scores: adds surge is the louder of the day's gain in percent
rostered over yesterday's level (floored at 1 percent; a gain of 2.5 times the level scores 1)
and today's Yahoo-wide adds against his median over at least three earlier days (log-scaled, 8
times scores 1), with his rank on the buzz index as the fallback until that history exists (first
1.0, fiftieth 0.3). Minutes trend is the smaller of the 7- and 14-day gains in minutes a game over
the rest-of-season projection, over 8 minutes, with floors of 2 and 4 games, and a usage gain over
5 points at half weight, combined by max. Value gap is (1 − rank/240)(1 − pct/50) for a rank
inside 120 on the league's own scoring and under 50 percent rostered. Opportunity is the
projected minutes of teammates in his position group listed out on ESPN for 14 or more days,
over 30 (15 for a teammate without a line), nothing for a player out himself, and it counts
toward the flag only beside another signal: on 2026-10-21 it alone made 14 of the watches in
each of two leagues, every guard on a team with two injured guards. Levels 0.8, 1.5 and 2.2 are
first guesses. `GET /seasons/{league}` carries the flags with their evidence and `GET
/flags/digest` every league's flagged players plus a markdown field for the public comment:
leagues by id, player names, Yahoo adds and percent-rostered changes and ESPN return dates, no
team or league names and no number derived from Basketball Monster; add and must-add players
with their evidence, the watch level folded into one line per league.

The explainer and the breakdown (#113). An "i" beside the Flag column's header on Waivers and
on the Flags card says what each signal reads and how it scores, the levels and the caveat that
they are first guesses, with every threshold taken from the API (`flag_config` on `GET
/seasons/{league}`, built from the constants in `season/flags.py`, so the text follows a
retune). Clicking a player's flag, on Waivers or on the Flags card, opens his breakdown under
the row: the four signals as bars from 0 to 1 with their evidence, the sum on a scale marked at
the three levels with the distance to the next one, and an "evaluate move" button. One breakdown
is open at a time across the page, and Esc closes it before the move drawer. A signal that
scores nothing because its input is missing says so rather than reading as a zero
(`flag_inputs.silent`: no rest-of-season export silences the minutes trend and the value gap, a
past-days export older than its limit the minutes trend, no injury report read the opportunity);
an opportunity score on its own is marked as not counted.

## The trade evaluator

The trading counterpart (from #79), built on the same data layer and objective. Given a
proposed trade (players on each side, between my roster and one opponent's, entered on the
dashboard), score both rosters before and after on expected categories won on the move model's
two horizons (resolved 2026-10-21: the rest of this week, each side against its own opponent,
and weeks 2–4 against the field with the other side's changed roster in it; the rest of the
season sits beside them since #151, "The rest of the season beside the horizons"), report the change for me and
for the counterparty per category and in total, the slot feasibility of each resulting roster
(an over-full side is not valid in Yahoo as entered and is shown with the least costly drop
named; a freed spot on my side is shown with its best free-agent fill, apart from the trade's own
change), the games and expected starts behind each traded player on both rosters, and the margin
that would make the trade neutral: the scale on the received players' counting production that
brings my three-week change to zero, read as "neutral if what I receive produces N percent of
its projection". The trade takes effect after the league's reject window (Yahoo's
`trade_reject_time`, two days when a league does not say; at once when nothing ratifies
trades), assumed accepted today, so the given players play for their old side until then; the
route answers 409 once the league's trade deadline has passed. The proposer (search the league for trades worth offering) stays a later
phase; the honest output of either is "no worse on our model", never "they will accept".
Nothing sends a proposal or acts in Yahoo.

## In the dashboard

Everything here lives inside the pickandroll web app and API, not in scripts or a second app
(user, 2026-10-21: "I need this to be inside pickandroll so it has UI to pick which league and
then UI to evaluate available waiver options"). The flow:

1. **Pick a league.** In season the landing page is a grid (#108): one card per league folder
   under `data/leagues/` with this week's score (mine first), the opponent, my place, the adds
   left, the pool's flag counts, the best recommended move with its gain over the three weeks
   after this one, and how old the snapshot is or why it did not read. The cards sort by most
   to gain. Clicking a card opens the season view at `?league=<id>`; a refresh link pulls a new
   snapshot from the public sources (the private league shows the extension's last post). The
   grid never solves a move on load: each card reads `GET /seasons/{id}/best`, which answers
   from the moves already solved today, and a league without an answer says "not solved yet"
   and solves on its button (`POST`). A Layout control in the top bar switches between this
   page and the draft-season one; auto shows the draft-season page while a league's draft runs
   or is less than fourteen days away. In season the drafts fold into one line and a Drafts
   drawer (the drafts ahead with Arm, live and finished drafts, the sessions, a New draft).
2. **Evaluate the waiver options.** The season view keeps the draft view's shape (rail, board
   column, cards drawer) with the board replaced by the Waivers table: every available player
   (free agents and waivers, with the clear date), his games left this week and over three
   weeks, his one-week and three-week gain if added in place of the best drop, that drop's name,
   the price of the next-best drop, percent rostered and its change, injury status, and the
   breakout flag with its evidence on hover and its breakdown under the row on a click (#113). Filters for position, status, NBA team, games this
   week and minimum percent rostered; sort by either gain. Selecting a row opens the move in
   the drawer: the add/drop pair, the per-category change for this week against the named
   opponent and over three weeks, and the alternatives with their prices.
3. **Cards in the drawer.** Roster (my players with games this week, IL and slot use),
   Matchup (both teams' projected totals and win odds per category for the week), Moves (the
   recommended pairs for the week under the add limit, then whom the keep rule keeps and the
   advice for the players who are out, #124), Trade (enter a proposal, read both
   sides' change), and the Flag digest (every flagged player across the league's pool).
   Built in #109 on the draft's rail and keys: the rail numbers the cards 1 Waivers, 2 Moves,
   3 Trade, 4 Flags, 5 My roster, 6 The league, 7 Strategy (#110, "The strategy engine"), 8
   Scorecard (#126, "Scorecard"); a
   digit opens a card in the drawer's top half
   and shift with a digit in its bottom half (Moves over Flags by default, the split
   draggable), and 1 gives the Waivers board the full width. `]` collapses the drawer to the
   rail, `/` jumps to the Waivers search, `j`/`k` move a highlight through its rows and Enter
   opens that player's move, `t` and `m` swap Trade and Moves, `r` refreshes a public league,
   `p` opens the Progress screen (#129), `?` lists the keys, and Esc leaves a field, then closes the move, then collapses the drawer.
   Card 6, The league (#116), has two tabs: Standings (the standings, the recorded weeks and the
   league's recent moves) and Matchups (this week's pairings with their live scores, mine
   first; a click on one opens its category totals as far as its matchup page was read, or says
   it was not read).
4. **Views** (#116). Where the board stands, the pane shows a view picked from a narrow drawer
   at its left edge: Waivers (`w`, the table above), Matchup (`h`), Season (`s`) and Lineup (`l`, #107). The chevron
   at its foot, or `[`, takes the drawer down to a 22 px handle whose dots mark the view on show;
   the view letters switch views either way, and the view and the drawer persist in the browser like the panel.
   1 Waivers shows the Waivers view first, and only there gives the board the full width. `/`
   comes back to the Waivers view for its search; `j`, `k` and Enter act only in it.
5. **The Matchup view** (#116), `GET /seasons/{league}/matchup?system=bbm|yahoo`. A scoreboard:
   the odds of winning the matchup large in the middle (the matchup odds above), Yahoo's count
   so far (won, lost, tied), the days left and the expected categories, my team on the left in
   amber and the opponent's on the right in blue, with the projection system's select. Then a
   row per category: my projected final with the week so far beneath it, a diverging bar (mine
   from the centre leftward, as long as my odds; theirs rightward, as long as theirs), the
   category and its odds as a pill (green at 60% or better, red at 40% or worse), and their
   final. The finals are the move model's own for the rest of the week (the same first day,
   starters, games and rates as the Moves card), so the view, Moves and Strategy agree.
   Beneath, my players and theirs: slot, games left, the nine per-game rates of the chosen
   system, Cats and Matchup. A player's Cats is the expected categories his team has with him
   less without him from the first day on, his starts going to the bench by the daily starters
   (the move model's drop path), and Matchup the same for the matchup odds; a player with no
   start left adds nothing. Theirs are what each adds for them. Sorted by Matchup, the players
   with no game left last. A team whose page was never read projects as an empty roster, and
   the view says so above the categories.
6. **The Season view** (#116, `s`), `GET /seasons/{league}/outlook?system=bbm|yahoo`. Every
   week left of my season. A summary line: the wins expected in the regular weeks left (their
   matchup odds summed), my record today, and how many of the named weeks are favoured (60% or
   better), toss-ups and underdogs (40% or worse). Then a strip of chips, one a week: its
   number, the opponent's name and the odds of winning it, filled green, amber or red by those
   lines, grey for a week against the field; a divider marks the playoffs. A click opens that
   week beneath the strip as a smaller scoreboard (the odds, the days and games, a bar per
   category) and my players that week with Cats and Matchup worked out as in the Matchup view;
   next week opens first.

   This week is the move model's own (the same span, opponent and week so far as the Matchup
   view). A later week is projected the same way from its Monday with today's rosters (nobody
   added or dropped; an O sits out this week only). Its opponent is the one the league page
   shown for that week pairs me with. A week whose pairs were never read, and a playoff week,
   is played against the field: its odds and finals are the average over every other team
   whose roster was read. The playoffs are the settings page's weeks (#107); before it is
   read they are estimated from v3's settings, one week a round of the bracket ending with the
   season's last week (six teams: weeks 20 to 22 of 22), because v3 names no playoff week; a
   private league whose settings page was not read begins them at the first week read with no
   pairs and none after it. A week without a roster faced has no odds and counts as none in the
   summary.
7. **The Lineup view** (#107, `l`), `GET /seasons/{league}/lineup?week=N&system=bbm|yahoo`
   ("Lineups"). The week's days across and the starting slots down, each cell the recommended
   starter; a day before the first day a change counts shows Yahoo's lineup as read, dimmed. A
   starter whom Yahoo's lineup has on the bench is lit amber. Under the slots, a Sit row (Yahoo's
   starters to take out) and a Bench row (the bench players who play that day); in the foot, the
   games each lineup starts and those Yahoo's loses. A day whose Yahoo lineup was not read is
   marked in its head. Above the grid: the week (this one and the moves' three after it), the
   rule and its source, the week's summary, the alerts (a cleared held occupant first, in red),
   and for the private league the pages its Chrome still needs. Under the grid, the held slots
   one by one with their occupants (a cleared one flagged: he blocks every add), the bound when
   the settings page is not read, and each active player eligible for a held slot with "eligible,
   1 open" or "eligible, IL full", so the user knows whether a swap is needed (#124). Nothing
   there sets a lineup.

   The schedule's sources: the public refresh reads the league page for each regular week
   after this one once (and again only while it lists no pairs), and the NBA schedule to the
   season's end. For the private league, `POST /seasons/{id}/record` answers with `ahead`, the
   league page of each week whose pairs are missing, and `scripts/season.py record` prints them
   as "schedule pages" after the record's own: for the user's signed-in Chrome to open once,
   read only, as the record's pages are.

The league page shown for another week (`?matchup_week=N`, the week select) used to land as
the league part and move the current week with it. It is stored as its own part,
`pairings/<week>`, and moves neither the standings nor the current week (#116).

Nothing on these screens acts in Yahoo. The add and drop stay the user's clicks on Yahoo's
pages; an armed queue through the extension is a later, opt-in phase.

### The freshness light (#153)

`GET /seasons/status` says whether the daily updates landed: the routine's run, the five
Basketball Monster exports (rest of season, this week, next week, the last 7 and 14 days, each
the newest file with its as-of), each league's Yahoo reads (a public league's last refresh
by its newest read, the private league's matchup, lineup, schedule and transactions pages) and
each league's recommendations (the moves set and the streaming plan from the decision log's
latest solve, against the newest projection export and Yahoo read; the strategy run and the
trade evaluation are made on request and carry no state). The states are decided in
`season/status.py`, on the Mac's clock, where the routine runs: **red** when something failed,
or is missing once the run is due at 06:30 (`ROUTINE_DUE`); **amber** when something is stale
or not due yet (a solve older than an input is amber, "re-solved on open"); **green**
otherwise. A league is its worst section with the exports; the whole is its worst league with
the exports and the run.

The this-week export is not due on a Sunday (#181). Basketball Monster's Remaining Week then
covers that one day and lists only the players with a game (139 on 2026-10-25). The routine
skips that export, and nothing downstream reads a one-day file: the week solve runs on per-game
rates and the schedule. On a Sunday on the light's own clock (never a file's dates), the row is
green, "not due on the week's last day", unless today's file is there, and it still names the
newest file. If the user imports a Sunday export by hand, the import's floor scales with the
span: `scripts/draft_prep/week.py`'s `min_players` asks for `ceil(300 × days / 7)` players on
`--this` (43 for one day), and 300 on `--next`.

The routine writes its run marker as its last step, `data/routine/daily.json`:

```json
{
  "started_at": "2026-10-23T05:00:12-05:00",
  "finished_at": "2026-10-23T05:52:40-05:00",
  "steps": {"<name>": {"status": "ok | failed | skipped", "detail": "<one line>"}},
  "exports": {"<kind>": "<file>"}
}
```

A failed step is red and a skipped one amber; a missing marker, or one from another day, reads
as "no run recorded today", amber before the due time and red after, never an error.

Every public refresh logs its start and its end, each a JSON line with the time it was written
(`at`) and the job's status, step, counts, error and warnings, to
`data/leagues/<id>/season/refreshes.jsonl`, and a line to the server's own log (uvicorn's
access lines carry no times). The light shows the service's own job, or after a restart the
last line of that log: a start with no end is red, "refresh never finished".

A refresh has a deadline (#166): `REFRESH_DEADLINE`, 300 seconds from its start. It is
checked before every read and between the steps, and whenever anything reads the job:
`?wait=true`'s wait, the status light, the season summary and a new refresh. Past it, the
job ends `failed`, and its error names the step, the last page read and the time it ran ("past
the 300-second deadline after 301 s: at available 26-50, reading …"). The end is logged, the light
reads "refresh failed" with that error, and the league's next refresh can start. A read in
flight at the deadline finishes or times out on its own socket timeout (30 seconds,
`public.HttpFetch`). A worker stuck in one stops at its next check and changes nothing: the
job keeps the deadline's end. The step the deadline cut is not retried in the same job, and the
broad handlers of the box scores, the schedule and the flag inputs let the deadline through
rather than turn it into warnings. One refresh runs at a time per league: `?wait=true` takes
the running job, or starts one, under the service's guard as the background path does, so two
waiting callers share one job.

## Phases

Each phase is one issue under the ADD/DROP tracker, built by fantasyEMISSARY in a worktree with
a PR, in dependency order; every phase ships its UI with its engine so the app is usable from
phase 2 on.

1. **Data layer and league picker.** `src/pickandroll/season/` (core, no I/O): a `Season` state
   with league settings, week calendar, the twelve rosters, the free-agent and waiver pool with
   ownership, injuries and the schedule. Loaders in `sources/yahoo/` for the three v3 endpoints
   and parsers for the public team, players and transactions pages, with saved pages as
   fixtures; `POST /seasons/{league}/snapshot` for the extension's reads of a private league,
   `POST /seasons/{league}/refresh` for the public sources, `GET /seasons/{league}` for the
   dashboard; snapshots written under `data/leagues/<id>/season/`. UI: the Leagues section on
   the landing page and a season view showing the roster and the raw available-player table.
2. **Weekly projection and the Waivers table.** Load the weekly and the rest-of-season
   Basketball Monster exports and Yahoo's own weekly projection from the signed-in players
   page; ESPN schedule cache; per-player weekly totals for the rest of this week and the next
   three weeks on the startable slots; the weekly category spread; per-category win odds
   against a named opponent. UI: the Waivers table with games, projections and ownership
   columns, and the Matchup card.
3. **Move optimiser and the Moves drawer.** Exact search on the #93 evaluator with both
   horizons (see the move model), deviation prices for alternative adds and drops, the weekly
   add limit, positions and IL;
   `GET /seasons/{league}/moves`. UI: the gain columns and the move drawer with per-category
   change and alternatives.
4. **Breakout flag.** The four signals, their scores and levels, the buzz index and past-days
   loaders; the flag column, hover evidence and the Flag digest card; the daily digest alert
   (built in #95; the alert is a scheduled session, see the decisions). The "i" explainer and
   the per-player breakdown under the row (#113).
5. **Trade evaluator.** `POST /seasons/{league}/trade` scoring both rosters before and after;
   the Trade card.
6. **Weekly recorder.** Every Monday, for each league: standings, each team's category totals
   and games played, the matchup results, and season-to-date lines for the drafted players
   (what #91's in-season test needs), appended under `data/leagues/<id>/season/weeks/`, with a
   small history view in the season rail. Built in #97: `POST /seasons/{league}/record?week=`
   writes one file per week, and recording it again writes only on a change (`revised_at`).
   A private league answers 409 with the pages it needs, for the extension to read in the
   user's Chrome. `GET /seasons/{league}/weeks` serves the Weeks block on the league card.
   `scripts/season.py record --all` prints one line per league and exits non-zero only when
   the API is unreachable. Since #126 a record also keeps the week's transactions, merged
   across the transactions pages read through it, for the Monday scorecard's moves, and since
   #149 my player-games lost to the lineup ("Lineups", games lost). The scheduled task `weekly-recorder-monday` runs it every Monday at
   06:00 on the Mac's clock and opens the private league's needed pages read-only in the
   user's Chrome (set up 2026-10-21).

Automation (queueing a claim through the extension with the draft's arming rule) is a later,
opt-in phase and is not in this batch.

## What the draft archive already gives us

`data/yahoo_history` holds drafts, standings, ADP and keepers for 2015-2025, not weekly rosters
or transactions. The weekly data starts accumulating this season once phases 1 and 7 run, so
they ship before the first full matchup week to capture the baseline. The first scoring week of
the prize leagues is week 1 (`current_week` 1 on 2026-10-21, season end 2027-04-04, 22 weeks).

## Decisions taken with the user

- **Leagues (2026-10-21):** all nine prize leagues from the public sources and the home league
  31822 through the extension's page reader, from day one. One engine, one season view per
  league.
- **Alert channel for the breakout digest:** a daily comment on the programme's tracker issue,
  posted by a scheduled session the way the draft scorecards were; a desktop notification can
  be added once the digest has run for a week. Set up 2026-10-21 as the scheduled task `breakout-digest-daily`: every day at 05:00
  on the Mac's clock it makes the day's Basketball Monster exports through the user's signed-in
  Chrome and imports them (rest of season with `draft_day.py projections`, this week and next
  week with `week --this` and `week --next`, past 7 and 14 days with `past-days`), refreshes the public leagues on the running API, reads `GET /flags/digest`
  and posts the markdown field on #99. The export buttons are clicked as real clicks, never from
  JavaScript: Chrome silently blocks script-triggered downloads after the first one of a session,
  and an import then re-saves an older download under the wrong name (seen 2026-10-22).
- **Default view on the Moves card:** the three-week gain, with the one-week gain beside it.
