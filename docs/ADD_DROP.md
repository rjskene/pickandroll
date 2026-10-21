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

## The move model

A move is (add, drop) or (add, nobody) when a slot is open, subject to the weekly add limit.
One LP: lock my roster minus the drops, candidates are the free agents available by the day the
claim would process (a free agent now, a waiver player on his clear date), maximise the
objective above over the horizon, with at most k drops and k adds. The deviation price of
every alternative add and every alternative drop is a re-solve, as on the board today, so the
card can say "dropping X instead costs 0.3 categories over the next three weeks".

Streaming is the W = 1 case with a games-heavy week: the solver will prefer the free agent with
four games to the better player with two, which is right for that week and wrong for the next,
so the card shows the one-week and the three-week answer side by side and the user chooses.

Waiver claims (resolved 2026-10-21): the first version prices free agents and lists waiver
players with their clear dates without pricing the claim. Priority cost and FAAB bids come
later, keyed by the league's waiver setting.

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

## The trade evaluator

The trading counterpart (from #79), built on the same data layer and objective. Given a
proposed trade (players on each side, between my roster and one opponent's, entered on the
dashboard), score both rosters before and after on expected categories won over the next three
weeks against the league's actual rosters and over the rest of the season, report the change
for me and for the counterparty per category and in total, the slot feasibility of each
resulting roster, the games behind each player over the horizon, and the margin that would make
the trade neutral. The proposer (search the league for trades worth offering) stays a later
phase; the honest output of either is "no worse on our model", never "they will accept".
Nothing sends a proposal or acts in Yahoo.

## In the dashboard

Everything here lives inside the pickandroll web app and API, not in scripts or a second app
(user, 2026-10-21: "I need this to be inside pickandroll so it has UI to pick which league and
then UI to evaluate available waiver options"). The flow:

1. **Pick a league.** The landing page, which today lists live draft rooms, gains a Leagues
   section: one row per league folder under `data/leagues/` with the league name, the week,
   my record, this week's opponent and when the snapshot was last refreshed. Clicking a row
   opens the season view at `?league=<id>`; a Refresh control pulls a new snapshot from the
   public sources (the private league shows the extension's last post and asks for a page
   visit when it is stale).
2. **Evaluate the waiver options.** The season view keeps the draft view's shape (rail, board
   column, cards drawer) with the board replaced by the Waivers table: every available player
   (free agents and waivers, with the clear date), his games left this week and over three
   weeks, his one-week and three-week gain if added in place of the best drop, that drop's name,
   the price of the next-best drop, percent rostered and its change, injury status, and the
   breakout flag with its evidence on hover. Filters for position, status, NBA team, games this
   week and minimum percent rostered; sort by either gain. Selecting a row opens the move in
   the drawer: the add/drop pair, the per-category change for this week against the named
   opponent and over three weeks, and the alternatives with their prices.
3. **Cards in the drawer.** Roster (my players with games this week, IL and slot use),
   Matchup (both teams' projected totals and win odds per category for the week), Moves (the
   recommended pairs for the week under the add limit), Trade (enter a proposal, read both
   sides' change), and the Flag digest (every flagged player across the league's pool).

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
3. **Move optimiser and the Moves drawer.** The LP with both horizons, deviation prices for
   alternative adds and drops, the weekly add limit, positions and IL;
   `GET /seasons/{league}/moves`. UI: the gain columns and the move drawer with per-category
   change and alternatives.
4. **Breakout flag.** The four signals, their scores and levels, the buzz index and past-days
   loaders; the flag column, hover evidence and the Flag digest card; the daily digest alert.
5. **Trade evaluator.** `POST /seasons/{league}/trade` scoring both rosters before and after;
   the Trade card.
6. **Weekly recorder.** Every Monday, for each league: standings, each team's category totals
   and games played, the matchup results, and season-to-date lines for the drafted players
   (what #91's in-season test needs), appended under `data/leagues/<id>/season/weeks/`, with a
   small history view in the season rail.

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
  be added once the digest has run for a week.
- **Default view on the Moves card:** the three-week gain, with the one-week gain beside it.
