# ADD/DROP: the in-season programme (waivers, breakout flag, trades)

Status: programme approved for build by the user on 2026-10-21 ("now I want to implement waiver
pickup assessment tool"). The design sketch of 2026-10-15 is kept below with its decisions
resolved; what the user still has to decide is in the last section. Issue #4 was the placeholder
for the module, #79 the trade brainstorm, #91 the in-season test the draft edge audit asks for.
The build runs as a tracker with one issue per phase (see "Phases").

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
| league settings, current week, week dates, roster slots, waiver and add rules | `pub-api.fantasysports.yahoo.com/fantasy/v3/settings/nba/<id>` (already used by `scripts/draft_day.py`) | `current_week`, `start_week`, `end_week`, `end_date`, `weekly_deadline`, and the `settings` block |
| player pool: positions, NBA team, injury status and note, season stats, Yahoo ranks, ADP | `.../v3/players/nba/<id>?format=json&projected=1&average=1` (744 players) | `inj`, `inj_full`, `inj_note`, `display_pos`, `season_stats`; no per-league ownership |
| team list | `.../v3/teams/nba/<id>` | names and ids only |
| each team's roster, including mine and this week's opponent's | the public team page `basketball.fantasysports.yahoo.com/nba/<id>/<team>` | roster names are in the served HTML (checked on 258901) |
| free agents and waivers with clear dates, percent rostered and its change | the public players page `/nba/<id>/players?status=A...` | the ownership column is served; whether the rows are server-rendered is the first thing phase 1 checks, else the extension reads the page |
| the league's own adds and drops | the public `/nba/<id>/transactions` page | |
| Yahoo-wide adds, drops and trades per player | the public buzz index `/nba/buzzindex` | the "surge in adds" signal for the breakout flag |
| this week's and next week's per-game projections with games, back-to-backs, minutes, injury, Yahoo ownership | Basketball Monster weekly export (`sources/bbm/fetch.py::weekly`, `this_week=True` for the rest of this week; `parse.py` already normalises it: `games`, `quality_games`, `back_to_backs`, `minutes`, `yahoo_owned_pct`, `bbm_adv_pct`, `injury`) | exported from the user's signed-in Chrome as the season export is, never with typed credentials |
| rest-of-season per-game projections | Basketball Monster season export, per-game | refreshed daily in season |
| recent production (minutes and rates over the last 7 or 14 days) | Basketball Monster past-days rankings (`fetch.py::rankings_past_days`) | the "minutes trend" signal |
| NBA schedule by team and date | ESPN's public scoreboard JSON (`site.api.espn.com/.../nba/scoreboard?dates=YYYYMMDD`), one call per date, cached under `data/schedule/` | NBA's own cdn file answers 403 |
| signed-in extras for every league (the user's Chrome, read-only): Yahoo's own projections per player for the next 7 and 14 days and the remaining games, last 7, 14 and 30 day totals, averages and standard deviations, percent rostered, roster status with the availability date, player notes; the home page's live matchup scores for every league | the players page and the home page in the user's signed-in Chrome, read with Claude in Chrome or the extension | checked 2026-10-21 on league 31822; a second weekly projection system for the blend the draft edge audit recommends, and the recent-production signal for the breakout flag |
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

## Phases

Each phase is one issue under the ADD/DROP tracker, built by fantasyEMISSARY in a worktree with
a PR; the order is the dependency order.

1. **Data layer.** `src/pickandroll/season/` (core, no I/O): a `Season` state with league
   settings, week calendar, the twelve rosters, the free-agent and waiver pool with ownership,
   injuries and the schedule. Loaders in `sources/yahoo/` for the three v3 endpoints and parsers
   for the public team, players and transactions pages, with saved pages as fixtures;
   `POST /seasons/{league}/snapshot` for the extension's reads of a private league and
   `GET /seasons/{league}` for the dashboard. A `scripts/season.py snapshot <league>` command
   that refreshes a league from the public sources and writes `data/leagues/<id>/season/`.
2. **Weekly projection.** Load the weekly and the rest-of-season Basketball Monster exports;
   ESPN schedule cache; per-player weekly totals for the rest of this week and the next three
   weeks on the startable slots; the weekly category spread; per-category win odds against a
   named opponent. Validate against the first weeks' real matchup totals as they arrive.
3. **Move optimiser.** The LP above with both horizons, deviation prices for alternative adds
   and drops, the weekly add limit, positions and IL. CLI first (`scripts/season.py moves
   <league>`), then the API route.
4. **Breakout flag.** The four signals, their scores and levels, the buzz index and past-days
   loaders, the daily digest.
5. **Dashboard.** A Moves card (recommended add/drop pairs with their one-week and three-week
   gain, drop candidates ranked by what losing them costs, the flag with its evidence), a
   Matchup card (both teams' projected totals and win odds per category for the week, games
   left per player) and a Trade card.
6. **Trade evaluator.** The route and the card's scoring described above; the proposer later.
7. **Weekly recorder.** Every Monday, for each league: standings, each team's category totals
   and games played, the matchup results, and season-to-date lines for the drafted players
   (what #91's in-season test needs), appended under `data/leagues/<id>/season/weeks/`.

Automation (queueing a claim through the extension with the draft's arming rule) is a later,
opt-in phase and is not in this batch.

## What the draft archive already gives us

`data/yahoo_history` holds drafts, standings, ADP and keepers for 2015-2025, not weekly rosters
or transactions. The weekly data starts accumulating this season once phases 1 and 7 run, so
they ship before the first full matchup week to capture the baseline. The first scoring week of
the prize leagues is week 1 (`current_week` 1 on 2026-10-21, season end 2027-04-04, 22 weeks).

## Open decisions for the user

- **Alert channel for the breakout digest:** a comment on a GitHub issue thread (as the draft
  scorecards were posted), a desktop notification from a scheduled session, or both.
- **Which leagues:** the nine prize leagues from the public sources, and the home league 31822
  through the extension; the engine is per league either way.
- **Default view on the Moves card:** the three-week gain, with the one-week gain beside it.
