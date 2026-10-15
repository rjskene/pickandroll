# ADD/DROP: the in-season waiver engine

Status: design sketch by fantasyMASTER, 2026-10-15, for the programme the user asked for after
the real draft ("begin working on our add/drop engine for waiver pickups"). Nothing here is built.
Decisions marked **open** need the user. Issue #4 is the placeholder for the in-season module.

## What it is for

Once the season starts the draft tool's question changes from "who do I take now" to "which
free agent do I add this week, and whom do I drop for him". The league is head-to-head, nine
categories, weekly matchups, so a move is worth exactly what it does to the categories I win in
the coming weeks, not what it does to a season-long z total. The same machinery as the draft
(category curve, win objective, LP over a roster with slots) applies, with three changes: the
horizon is weeks instead of picks, totals depend on the NBA schedule, and the opponent is one
known team per week rather than a population.

## Objective

Expected categories won over a horizon of W weeks (**open**: W = 1 for the pure streaming view,
W = 3 or 4 for the "is he worth a roster spot" view; the card should show both):

    sum over weeks w, categories c  of  P(my total_{w,c} > opponent_{w}'s total_{w,c})

where a player's weekly total is his per-game projection times the games his NBA team plays in
that week, on the roster slots I can actually start (Yahoo's daily lineup: ten starters, so a
day with twelve players with games wastes two). The probability comes from the weekly spread
of each category, which is far wider than the season spread the draft curve uses; it is fit
from per-game variance and games played, or from the league's own weekly box scores once a few
weeks exist (the Yahoo matchup pages record every week's totals per team).

The season-long table enters as a tie-break only (**open**): in a head-to-head each-category
league, standings are weekly category wins, so there is no separate "roto" objective to blend.

## Inputs

| input | source | notes |
|---|---|---|
| my roster, IL, positions | Yahoo team page | extension content script on the team page, same pattern as the draft room, or the Yahoo Fantasy API once issue #1's approval lands |
| free-agent pool with status | Yahoo players page (free agents + waivers, with waiver clear dates) | the extension already parses the players table |
| rest-of-season projections per game | Basketball Monster export (`scripts/bbm_fetch.py`) | refreshed daily in season; injuries are already in BBM's per-game and games numbers |
| NBA schedule by team and week | public schedule (NBA API or a static season file in `data/`) | games per team per matchup week; all-star break and the weeks with 2 or 5 games are where streaming pays |
| this week's and next week's opponent rosters | Yahoo matchup page / league rosters | the extension or the API |
| league rules | Yahoo settings page | weekly add limit, waiver type (priority or FAAB), waiver period, IL slots, roster size |

Nothing in this module handles credentials; the extension reads pages the user has open, the
API path uses the user's own OAuth consent.

## The move model

A move is (add, drop) or (add, nobody) when a slot is open, subject to the weekly add limit.
One LP: lock my roster minus the drops, candidates are the free agents available by the day the
claim would process (a free agent now, a waiver player on his clear date), maximise the
objective above over the W-week horizon, with at most k drops and k adds. The deviation price
of every alternative add and every alternative drop is a re-solve, as on the board today, so the
card can say "dropping X instead costs 0.3 categories over the next three weeks".

Streaming is the W = 1 case with a games-heavy week: the solver will prefer the free agent with
four games to the better player with two, which is right for that week and wrong for the next,
so the card shows the one-week and the horizon answer side by side and the user chooses.

Waiver priority (**open**, depends on the league's setting): with priority waivers a claim that
succeeds moves me to the back of the line, so a claim is worth its gain minus the expected value
of the priority spent; with FAAB the bid is a price and the engine suggests a bid from the
player's gain and the league's bidding history. First version: free agents only, waiver claims
listed but not priced.

## Phases

1. **Data layer.** Roster, free agents, opponent roster and schedule into a `Season` state object
   in `src/pickandroll/season/` (core, no I/O) fed by loaders in `sources/`. Yahoo page parsing in
   the extension, a `POST /seasons/{league}/snapshot` route to receive it. Test with fixtures.
2. **Weekly projection.** Per-player weekly totals from per-game projections and the schedule;
   the weekly category spread; per-category win odds against a named opponent. Validate against
   the first weeks' real matchup totals as they arrive.
3. **Move optimiser.** The LP above with a horizon of weeks, deviation prices, add-limit and
   positions. Harness: replay last season's weekly rosters where the archive allows and score
   the moves the engine would have made.
4. **Dashboard.** A Moves card: this week's recommended add/drop pairs with their one-week and
   horizon gain, the drop candidates ranked by what losing them costs, the streaming view of
   games per team this week, and the opponent's projected totals per category.
5. **Automation (later, opt-in).** Queue a claim from the dashboard through the extension, with
   the same arming rule as the draft: nothing is submitted unless the user armed it.

## What the draft archive already gives us

`data/yahoo_history` holds drafts, standings, ADP and keepers for 2015-2025, not weekly rosters
or transactions. The weekly data starts accumulating this season once the data layer is built,
so phase 1 should ship before the first full matchup week to capture the baseline.

## Open decisions for the user

- Horizon W and whether the Moves card defaults to the one-week or the multi-week answer.
- Free agents only for the first version, or waiver claims priced from day one.
- Extension page parsing versus the Yahoo API for the in-season data (the API needs the
  approval that issue #1 tracks; the extension works today).
- Whether the same engine serves the cash leagues the user plans to join (it should: the state
  object is per league, like the draft session).
