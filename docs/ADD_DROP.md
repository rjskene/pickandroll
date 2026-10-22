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
| league settings, current week, roster slots, waiver and add rules | `pub-api.fantasysports.yahoo.com/fantasy/v3/settings/nba/<id>` (already used by `scripts/draft_day.py`) | `current_week`, `start_week`, `end_week`, `end_date`, `weekly_deadline`, and the `settings` block; no week dates |
| week dates | the public team page on a date, `/nba/<id>/<team>?date=YYYY-MM-DD`, whose "Week N stats may change" line names that day's matchup week | one request per Monday of the season, cached for every league in `data/leagues/_shared/season/calendar.json` (#92); 2026-27 has 22 weeks, week 1 Oct 19-25, week 17 Feb 15-28 across the All-Star break, week 22 Mar 29-Apr 4 |
| standings, waiver priority, FAAB left, moves, this week's pairs | the public league page `/nba/<id>` | the `standingstable` and the week's `matchup?week=&mid1=&mid2=` links |
| a matchup's week totals and score | the public matchup page `/nba/<id>/matchup?week=W&mid1=A&mid2=B` | each team's category totals; a points league adds Yahoo's original and live projected points |
| player pool: positions, NBA team, injury status and note, season stats, Yahoo ranks, ADP | `.../v3/players/nba/<id>?format=json&projected=1&average=1` (744 players) | `inj`, `inj_full`, `inj_note`, `display_pos`, `season_stats`; no per-league ownership |
| team list | `.../v3/teams/nba/<id>` | names and ids only |
| each team's roster, including mine and this week's opponent's | the public team page `basketball.fantasysports.yahoo.com/nba/<id>/<team>` | roster names are in the served HTML (checked on 258901) |
| free agents and waivers with clear dates, percent rostered and its change | the public players page `/nba/<id>/players?status=A&pos=P&stat1=R_O&sort=R_PO&sdir=1&count=<offset>` | checked in #92 on 258901: the rows are server-rendered, 25 a page; the Research view `R_O` carries roster status with the waiver date, percent rostered and started with the day's change, and Yahoo-wide adds, drops and trades. The same public page serves the stat views too, so a public league needs no sign-in for them: `S_PS7` and `S_PS14` (Yahoo's projections for the next 7 and 14 days), `S_PSR` (the remaining games), `S_L7`, `S_L14`, `S_L30` (last 7, 14 and 30 days, totals and averages) and the standard deviations (`S_SDL14` and the like) |
| the league's own adds and drops | the public `/nba/<id>/transactions` page | |
| Yahoo-wide adds, drops and trades per player | the public buzz index `/nba/buzzindex` | the "surge in adds" signal for the breakout flag |
| this week's and next week's per-game projections with games, back-to-backs, minutes, injury, Yahoo ownership | Basketball Monster weekly export (`sources/bbm/fetch.py::weekly`, `this_week=True` for the rest of this week; `parse.py` already normalises it: `games`, `quality_games`, `back_to_backs`, `minutes`, `yahoo_owned_pct`, `bbm_adv_pct`, `injury`) | exported from the user's signed-in Chrome as the season export is, never with typed credentials |
| rest-of-season per-game projections | Basketball Monster season export, per-game | refreshed daily in season |
| recent production (minutes and rates over the last 7 or 14 days) | Basketball Monster past-days rankings (`fetch.py::rankings_past_days`) | the "minutes trend" signal |
| NBA schedule by team and date | ESPN's public scoreboard JSON (`site.api.espn.com/.../nba/scoreboard?dates=YYYYMMDD`), one call per date, cached under `data/schedule/` | NBA's own cdn file answers 403 |
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
  `bbm_week_this_*` (the rest of this week) and `bbm_week_next_*`, each with the `.json`
  sidecar `sources/bbm/fetch.py` writes (`start`, `end`); a this-week export without one counts
  only on the day it was made.
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

IL: an active player whose status the slot accepts moves into an open IL or IL+ slot for free,
which opens a spot without a drop; players already in IL, IL+ or NA slots stay put and are not
drop candidates. Slot eligibility is a configurable set, a best guess until a league with IL
slots is seen: IL accepts INJ, O and OFS; IL+ also GTD; NA accepts NA.

Add limit: k is the league's weekly limit minus the adds already made this week, counted from
the transactions page; when that page does not reach back to the week's start the payload says
the count is unknown and uses the full limit.

Waiver claims (resolved 2026-10-21): the first version prices free agents and lists waiver
players with their clear dates without pricing the claim. Priority cost and FAAB bids come
later, keyed by the league's waiver setting.

## The strategy engine (#110)

The Moves card answers one horizon at a time. The Strategy card weighs this week against the rest
of the season on one value, for a weight λ:

    λ · (expected categories this week) + (1 − λ) · (weeks left) · (a later week's)

where a later week is the three weeks ahead averaged: "rest of season, from the three weeks
ahead", the three-week horizon taken as the stationary later week, times the calendar's weeks
after this one. Four weights make the frontier: this week alone (λ = 1); this week as much as all
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
  limit with a set, or found none. It makes no held-slot moves; the search does.

The card recommends whichever set is better on the weight's exact value, and says which: the
search's, the program's, or both when they found the same adds with the same drops on the same
days. A program's set that a re-solve beats while it is priced becomes the search's answer, with
a note. Option B is one switch, `program_only`: the program's set whenever it solves to the gap,
the search's only when the program hits its limit or finds no set; the default stays on A.

The field curve uses every game of the other teams' rosters rather than their projected starts.
The program's count cap ignores positions, so it overstates my own starts by the same token; on
the prize leagues' data an isolated check found the starts curve equal or worse at every point.

At the program's solution each player also gets a first-order value: the curves' slopes there
times his line over every game he plays, weighted as the program weighs the horizons. The card
lists the pool's highest outside the set and my lowest not dropped, as a ranking of whom to look
at next, not a price (the prices are the re-solves').

`GET /seasons/{id}/strategy?system=` returns today's run for the snapshot as far as it got and
never solves; `POST` with `pool`, `weights`, `lock` (my players never dropped, repeated) and
`program_only` starts one, replacing an older run of that league and system (`wait=true` blocks
until it finishes, for tests). A run searches every weight, then solves the programs in a
background process pool while the searches' sets are priced, then chooses. The card is the rail's
seventh: it opens on the natural weight with a Solve button and solves nothing on load; the
frontier plots each weight's set by its gain this week across and over the rest of the season
up, hollow the search's, solid the program's, half both, the natural weight ringed; a weight's
tab shows the set with a lock on each drop, the categories before and after, the first-order
lists and the solvers' seconds and sizes. Like every card it says "recommended", never
"optimal", and nothing in it acts in Yahoo.

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
and weeks 2–4 against the field with the other side's changed roster in it; a rest-of-season
horizon needs the full-season schedule cache and is a follow-up), report the change for me and
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
   recommended pairs for the week under the add limit), Trade (enter a proposal, read both
   sides' change), and the Flag digest (every flagged player across the league's pool).
   Built in #109 on the draft's rail and keys: the rail numbers the cards 1 Waivers, 2 Moves,
   3 Trade, 4 Flags, 5 My roster, 6 The league, 7 Strategy (#110, "The strategy engine"); a
   digit opens a card in the drawer's top half
   and shift with a digit in its bottom half (Moves over Flags by default, the split
   draggable), and 1 gives the Waivers board the full width. `]` collapses the drawer to the
   rail, `/` jumps to the Waivers search, `j`/`k` move a highlight through its rows and Enter
   opens that player's move, `t` and `m` swap Trade and Moves, `r` refreshes a public league,
   `?` lists the keys, and Esc leaves a field, then closes the move, then collapses the drawer.

Nothing on these screens acts in Yahoo. The add and drop stay the user's clicks on Yahoo's
pages; an armed queue through the extension is a later, opt-in phase.

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
   the API is unreachable. The scheduled task `weekly-recorder-monday` runs it every Monday at
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
  Chrome and imports them (rest of season, past 7 and 14 days; this week and next week once the
  `week` import exists), refreshes the public leagues on the running API, reads `GET /flags/digest`
  and posts the markdown field on #99. The export buttons are clicked as real clicks, never from
  JavaScript: Chrome silently blocks script-triggered downloads after the first one of a session,
  and an import then re-saves an older download under the wrong name (seen 2026-10-22).
- **Default view on the Moves card:** the three-week gain, with the one-week gain beside it.
