// The draft track (#284): nine steps, from the stat line to the room. Every card is bullets:
// key ideas with their sub-ideas, two levels, no paragraphs (the user's rule, #282). Sources
// are docs/DESIGN.md, docs/KEEPERS.md, docs/YAHOO_SYNC.md and the extension's constants.
import type { Track } from "../types";

export const draft: Track = {
  id: "draft",
  title: "Draft",
  short: "Draft",
  lede: "Every pick is the first move of a plan for all my remaining picks.",
  labels: ["Projections", "Pool & z", "Survival", "Objective", "Plan", "Price → pick", "Solve ahead", "Keepers", "Yahoo room"],
  loop: { from: 8, to: 2, label: "re-solved after every pick" },
  steps: [
    {
      id: "projections",
      title: "Start with a stat line, not a rank",
      kicker: "projections",
      figure: "export-row",
      bullets: [
        {
          text: "The input is a [projection-set|rest-of-season export] from the subscriber projection source, one row per player",
          sub: [
            "games, minutes, the counting totals, makes and attempts for both percentages",
            "totals over the horizon, never per game: a 20-game horizon is a smaller export, not a rescaled one",
          ],
        },
        {
          text: "Players are matched to Yahoo ids by normalized name",
          sub: ["an alias table covers the handful that differ"],
        },
        { text: "The model never sees a rank or a dollar value: only the stat line" },
      ],
      source: ["docs/DESIGN.md · projections", "the export reader under src/"],
      example: {
        title: "Five rows of a rest-of-season export",
        lead: [
          {
            text: "Five players, A to E, with 58 to 70 games left; every number is made up",
            sub: ["one row per player: totals over the games left, never per game"],
          },
        ],
        table: {
          head: ["Player", "G", "PTS", "3PM", "REB", "AST", "STL", "BLK", "TO", "FGM", "FGA", "FTM", "FTA"],
          num: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
          rows: [
            ["Player A", "68", "1,750", "190", "340", "420", "85", "25", "210", "610", "1,290", "340", "390"],
            ["Player B", "70", "1,330", "60", "760", "210", "70", "120", "150", "520", "1,000", "230", "330"],
            ["Player C", "62", "1,280", "150", "410", "300", "95", "40", "140", "460", "1,030", "210", "250"],
            ["Player D", "66", "980", "210", "280", "330", "60", "20", "120", "350", "810", "70", "90"],
            ["Player E", "58", "720", "30", "520", "90", "45", "95", "80", "300", "560", "90", "160"],
          ],
        },
        read: [
          { text: "Player A's 1,750 points over 68 games is 25.7 a game; the model keeps the 1,750" },
          {
            text: "Percentages come as makes and attempts: Player B makes 520 of 1,000, a .520 shooter",
            sub: ["the next step turns them into impact, so they add up across a roster"],
          },
          { text: "A player whose name differs on Yahoo is matched through the alias table" },
        ],
      },
    },
    {
      id: "pool",
      title: "Score every stat against the players who will be drafted",
      kicker: "the pool and z-scores",
      figure: "pool-passes",
      bullets: [
        {
          text: "[z-score|Z-scores] are taken against the [pool|draft pool]: the players who will actually be drafted",
          formula: "zscore",
          sub: ["a counting total: how many of the pool's spreads it sits above the pool's mean; turnovers negated"],
        },
        {
          text: "The pool takes three passes: score everyone, keep as many as the rosters hold, measure again on those",
          sub: ["by pass 3 it keeps the players it measured against, or nearly: settled; always three, never a test"],
        },
        {
          text: "Each counting category's mean and spread come from the pool alone; the spread is its standard deviation",
          formula: "pool-spread",
          sub: ["the population one: divided by the pool's size, not one less, since the pool is the whole group"],
        },
        {
          text: "Percentages are scored as impact: the makes above a pool-average shooter on the same attempts",
          formula: "impact",
          sub: ["impact adds linearly over a roster: a team's percentage is exact, never a mean of percentages"],
        },
        {
          text: "The pool's impacts average exactly zero, so the spread of impact alone sets the scale",
          formula: "impact-spread",
          sub: ["the pool's percentage times its attempts is its makes: that is what the percentage is"],
        },
      ],
      source: ["docs/DESIGN.md · the pool and z-scores", "projections/zscores.py and optim/pool.py under src/"],
      example: {
        title: "Eight players, a pool of four, pass by pass",
        lead: [
          {
            text: "Eight players, A to H, two categories, and rosters that hold four: the pool is four",
            sub: ["each pass takes the pool's mean and spread, rescores all eight, and keeps the top four by total"],
          },
          { text: "Each pass column is the total z; every number is made up" },
        ],
        table: {
          head: ["Player", "PTS", "REB", "Pass 1", "Pass 2", "Pass 3"],
          num: [1, 2, 3, 4, 5],
          rows: [
            ["Player A", "1,170", "890", "1.93 kept", "0.59 kept", "0.07 kept"],
            ["Player B", "1,520", "540", "0.54 kept", "−0.09 kept", "−0.24 kept"],
            ["Player C", "1,760", "440", "0.48 kept", "0.27 kept", "0.20 kept"],
            ["Player D", "1,170", "660", "0.47 kept", "−0.78 out", "−1.00"],
            ["Player E", "1,860", "310", "−0.11", "−0.10 in", "−0.03 kept"],
            ["Player F", "1,090", "550", "−0.43", "−1.75", "−1.81"],
            ["Player G", "720", "550", "−1.31", "−3.23", "−3.20"],
            ["Player H", "640", "540", "−1.57", "−3.61", "−3.55"],
          ],
        },
        read: [
          {
            text: "Pass 1 measures against all eight and keeps A, B, C and D",
            sub: ["Player E's 1,860 points are 1.48 spreads up, not enough with only 310 rebounds"],
          },
          {
            text: "Pass 2 measures against A to D: the points mean rises to 1,405 and its spread tightens to 250",
            sub: ["E's points are now 1.82 spreads up: E crosses in at −0.10, D drops out at −0.78"],
          },
          { text: "Pass 3 measures against A, B, C and E and keeps the same four: settled" },
        ],
      },
    },
    {
      id: "survival",
      title: "How likely is he still there at my next pick?",
      kicker: "survival",
      figure: "survival",
      bullets: [
        {
          text: "A value becomes a plan only through [survival], always read conditionally from the current pick",
          sub: ["what counts is the chance he lasts from here to my pick, not from pick one"],
        },
        {
          text: "First the league's own record, shrunk toward the ADP formula by how many drafts it holds",
          formula: "league-blend",
          sub: ["rows by [keeper-adp|keeper-adjusted ADP], with the share never drafted"],
        },
        { text: "Then a simulated table of 300 drafts, when the league has no archive" },
        {
          text: "Then the [adp|ADP] formula, with the league's ADP-bias shift, where a table has no row",
          formula: "adp-survival",
          sub: ["a normal draft slot around his ADP, wider for later picks"],
        },
        { text: "The record carries what the formula cannot: the players who are never drafted at all" },
      ],
      source: ["docs/DESIGN.md · survival", "availability/survival.py and availability/league.py under src/"],
      example: {
        title: "Five players, my pick now at 21 and the next at 28",
        lead: [
          {
            text: "I draft 4th of 12, so my picks are 4, 21, 28, 45 and so on; I am on the clock at 21",
            sub: ["the ADP formula alone here, with no league record and no ADP bias"],
          },
        ],
        table: {
          head: ["Player", "ADP", "spread", "lasts to 21", "lasts to 28", "from 21 to 28"],
          num: [1, 2, 3, 4, 5],
          rows: [
            ["Player A", "18", "4.2", "0.24", "0.01", "0.04"],
            ["Player B", "24", "5.1", "0.72", "0.22", "0.30"],
            ["Player C", "30", "6.0", "0.93", "0.63", "0.68"],
            ["Player D", "36", "6.9", "0.99", "0.88", "0.89"],
            ["Player E", "50", "9.0", "1.00", "0.99", "0.99"],
          ],
        },
        read: [
          { text: "Player A is still here at 21, past his ADP; he will not last to 28", sub: ["take him now, or plan without him"] },
          { text: "Player C lasts to 28 about two times in three, read from now" },
          { text: "The last column is the one the plan uses: each player is known to be here at 21" },
        ],
      },
    },
    {
      id: "objective",
      title: "Count the categories the roster is expected to win",
      kicker: "the objective",
      figure: "objective",
      bullets: [
        {
          text: "The roster is scored as [ecw|expected categories won]: per category, the chance it beats a league team, summed",
          formula: "ecw",
          sub: [
            "against the league's mean and spread of team totals in that category: the [curve]",
            "fitted on 36,000 simulated teams, or on the league's own rosters blended toward that prior",
          ],
        },
        {
          text: "A category the board has made unwinnable has near-zero [marginal|marginal value], so the plan stops paying for it",
          sub: ["a punt can emerge; nobody chooses one"],
        },
        {
          text: "The solver carries the S-curve as straight pieces, joined at fixed points",
          formula: "piecewise-phi",
          sub: ["a half, one and a half and two and a half spreads either side of the mean"],
        },
      ],
      source: ["docs/DESIGN.md · the objective", "optim/objective.py under src/"],
      example: {
        title: "One roster's nine categories against the league",
        lead: [
          {
            text: "The roster's projected total z in each category, against the league's curve",
            sub: ["the curve: the mean and spread of team totals, made up for this example"],
          },
        ],
        table: {
          head: ["Cat", "total", "mean", "spread", "in spreads", "P(win)", "per extra z"],
          num: [1, 2, 3, 4, 5, 6],
          rows: [
            ["PTS", "6.2", "4.0", "3.0", "0.73", "0.768", "0.10"],
            ["3PM", "2.0", "3.5", "3.1", "−0.48", "0.314", "0.11"],
            ["REB", "1.0", "4.0", "3.2", "−0.94", "0.174", "0.08"],
            ["AST", "4.5", "4.0", "2.8", "0.18", "0.571", "0.14"],
            ["STL", "5.0", "3.0", "2.5", "0.80", "0.788", "0.12"],
            ["BLK", "−3.5", "3.5", "3.0", "−2.33", "0.010", "0.01"],
            ["TO", "−1.5", "0.0", "2.6", "−0.58", "0.282", "0.13"],
            ["FG%", "2.2", "1.5", "2.4", "0.29", "0.615", "0.16"],
            ["FT%", "3.0", "1.5", "2.5", "0.60", "0.726", "0.13"],
          ],
        },
        read: [
          { text: "The nine chances sum to 4.25 expected categories won" },
          {
            text: "Blocks sit 2.3 spreads below the mean: one more z there buys 0.01 of a category",
            sub: ["the same z in field goals buys 0.16, so the plan stops paying for blocks"],
          },
          { text: "Nobody chose to give up blocks: the board made them unwinnable" },
        ],
      },
    },
    {
      id: "plan",
      title: "Plan every remaining pick, act on the first",
      kicker: "the plan",
      figure: "plan",
      bullets: [
        {
          text: "The [horizon-plan|rolling-horizon model] plans one player for each of my remaining picks",
          formula: "plan-value",
          sub: [
            "each player's value discounted by the chance he lasts to that pick",
            "every slot filled once, every player at most once, the final roster placed in Yahoo's slots",
            "stars go early; late picks lean on players who will actually be there",
          ],
        },
        {
          text: "Solved as a mixed-integer program with HiGHS through PuLP",
          sub: ["the 80 best availability-weighted candidates per pick", "to a 1% gap; the incumbent is kept when the 20 s limit hits"],
        },
        { text: "Only the first pick is acted on; after the next real pick the whole plan is solved again" },
        { text: "My [keeper|keepers] are locked in and their rounds are not planned" },
      ],
      source: ["docs/DESIGN.md · the rolling-horizon plan", "optim/horizon.py under src/"],
      example: {
        title: "The plan at my pick 21: who goes where",
        lead: [
          {
            text: "Total z over the nine categories, for brevity; the solver keeps each category apart",
            sub: ["lasts: the chance he is on the board at that pick, read from now"],
          },
        ],
        table: {
          head: ["My pick", "player", "total z", "lasts", "z × lasts", "in the plan"],
          num: [0, 2, 3, 4],
          rows: [
            ["21", "Player A", "5.2", "1.00", "5.20", "yes: the pick now"],
            ["28", "Player C", "4.0", "0.68", "2.72", "no"],
            ["28", "Player D", "3.2", "0.97", "3.10", "yes"],
            ["45", "Player E", "2.6", "0.90", "2.34", "yes"],
          ],
        },
        read: [
          { text: "At 28 the plan takes Player D: less z than Player C, but he will be there" },
          { text: "Only pick 21 is made; after the next real pick the whole plan is solved again" },
        ],
      },
    },
    {
      id: "price",
      title: "Price every candidate, show the recommendation and its ties",
      kicker: "the price, and the pick",
      figure: "price",
      bullets: [
        {
          text: "Each candidate is forced to be the first pick in turn; the objective lost is his [price] now",
          formula: "price",
          sub: ["waiting risk included: the chance he is gone by my next pick is already in the plan"],
        },
        { text: "Candidates within 0.05 categories of the best are a [tie], listed in ADP order, not a decree" },
        {
          text: "Each step of the plan can ask what my roster looks like if this candidate is gone",
          sub: ["the pick is a choice with its alternatives visible"],
        },
        { text: "The pick shown is recommended; the user drafts" },
      ],
      source: ["docs/DESIGN.md · prices and ties", "api/solver.py under src/"],
      example: {
        title: "Four candidates priced at pick 21",
        lead: [
          {
            text: "Each candidate is forced to be my pick now and the plan solved again",
            sub: ["the best plan, nothing forced, is worth 7.42 expected categories won"],
          },
        ],
        table: {
          head: ["Candidate", "forced first", "price", "reading"],
          num: [1, 2],
          rows: [
            ["Player A", "7.42", "0.00", "recommended"],
            ["Player B", "7.39", "0.03", "a tie: within 0.05"],
            ["Player C", "7.21", "0.21", "a fifth of a category"],
            ["Player D", "6.98", "0.44", "almost half a category"],
          ],
        },
        read: [
          { text: "Players A and B are a tie: listed in ADP order, and the choice is the user's" },
          { text: "A price already counts the risk of waiting: the plan carries each pick's survival" },
        ],
      },
    },
    {
      id: "solve-ahead",
      title: "Have the answer before the clock starts",
      kicker: "solve ahead",
      figure: "solve-ahead",
      bullets: [
        {
          text: "Time limits are a safety net, not the budget",
          sub: ["a background solver works as soon as the session exists, and again after every change"],
        },
        {
          text: "One round",
          sub: [
            "snapshot the board under the session lock, so picks can land while it runs",
            "solve the plan, then price every candidate: first order from the curve's slopes, then exactly",
            "solve the \"if he is gone\" scenarios, publish a recommendation event",
          ],
        },
        {
          text: "A full round on a 234-player export takes about 20 s; changes mid-solve coalesce into one more",
          sub: ["the shown result is marked stale while a re-plan runs", "a pick made mid-flight is at most one pick stale by my turn"],
        },
        { text: "In a room: three candidates, no scenarios, 5 s, inside Yahoo's 30 s pick clock" },
      ],
      source: ["docs/DESIGN.md · the background solver", "docs/YAHOO_SYNC.md · the plan budget", "api/solver.py under src/"],
      example: {
        title: "One round while the room keeps picking",
        lead: [{ text: "Pick 17 lands; my turn is pick 21; the seconds count from the landing" }],
        table: {
          head: ["Second", "what happens"],
          num: [0],
          rows: [
            ["0", "pick 17 lands; the board is snapshotted under the session lock"],
            ["0–9", "the plan is solved on the snapshot"],
            ["6", "pick 18 lands mid-solve: the result is marked stale, one more round queued"],
            ["9–15", "every candidate priced: first order at once, then exactly"],
            ["15–20", "the \"if he is gone\" scenarios; the recommendation is published"],
            ["20", "the queued round starts on the board with pick 18 and any picks since"],
          ],
        },
        read: [{ text: "Picks 19 and 20 fold into that one round: by my turn the answer is at most one pick old" }],
      },
    },
    {
      id: "keepers",
      title: "Keepers are picks already made",
      kicker: "keepers",
      figure: "keeper-snake",
      bullets: [
        {
          text: "A [keeper] is (team position, round, player); his overall pick follows from the draw",
          formula: "snake",
          sub: ["a snake draft: odd rounds run forward, even rounds back"],
        },
        {
          text: "The pick log stays contiguous",
          sub: [
            "when the clock reaches a keeper slot his pick is appended; a different player there is refused",
            "keepers sit on their teams' rosters from pick one",
          ],
        },
        {
          text: "Every remaining player's ADP moves up by the keepers ranked ahead of him",
          sub: ["in that [keeper-adp|keeper-adjusted] space the league drafts to ADP with no bias"],
        },
      ],
      source: ["docs/KEEPERS.md", "draft/state.py and availability/adp.py under src/"],
      example: {
        title: "Two keepers from draft position 9 in a 12-team snake",
        lead: [{ text: "Odd rounds run from position 1 to 12, even rounds from 12 back to 1" }],
        table: {
          head: ["Keeper's round", "the round runs", "overall pick"],
          num: [0, 2],
          rows: [
            ["5", "1 to 12", "57"],
            ["10", "12 to 1", "112"],
          ],
        },
        read: [
          { text: "Each keeper's pick is appended to the log when the clock reaches 57 and 112" },
          {
            text: "A player with ADP 40 and six keepers ranked ahead of him moves to 34",
            sub: ["keeper-adjusted ADP: in that space the league drafts to ADP"],
          },
        ],
      },
    },
    {
      id: "room",
      title: "Mirror the room, and click only when armed",
      kicker: "the Yahoo room",
      figure: "yahoo-room",
      wide: true,
      bullets: [
        {
          text: "[mirror|Mirror]: Yahoo pushes nothing to the API, so the draft page itself is the reader",
          sub: [
            "the extension wraps the WebSocket Yahoo opens, never sends on it; each room pick lands as an event",
            "the room is the truth for the board: a session pick that disagrees is replaced, logged as a conflict",
            "manual picks, in Yahoo or in the app, are always possible and never overridden",
          ],
        },
        {
          text: "[armed|Armed]: the user arms the seat from the side panel; no session arms it for them",
          sub: [
            "on the turn the tab holds the plan route for a fresh solve of the current board",
            "then clicks the candidate's row, with a quick re-click",
            "then falls back to the search box, a scroll, or Yahoo's queue for the current pick only",
          ],
        },
        { text: "An [act-at] setting holds the click until the clock is down to 12 to 30 s, unless the user picks first" },
        {
          text: "Three hops: page.js listens, content.js tracks the room, worker.js is the only API caller",
          sub: ["picks idempotent by overall; a restart rebuilds the room from its log", "a hidden tab's timers run in a Web Worker"],
        },
      ],
      source: ["docs/YAHOO_SYNC.md", "extension/lib/drafter.js · the clock's constants", "api/yahoo_room.py under src/"],
      example: {
        title: "A rival's pick, then my armed turn",
        lead: [{ text: "A 30 s pick clock; the seat is armed, with the act-at set to 15 s" }],
        table: {
          head: ["Moment", "what happens"],
          rows: [
            ["pick 39, in Yahoo", "page.js reads the frame; content.js turns it into a room event"],
            ["a moment later", "worker.js posts the pick; the session plans again"],
            ["pick 40, 30 s left", "the tab asks the plan route for a fresh solve of this board"],
            ["15 s left", "the act-at releases the click: the candidate's row, then a quick re-click"],
            ["the pick frame", "the room confirms; the session logs pick 40 as mine"],
          ],
        },
        read: [
          { text: "Not armed, the mirror still lands every pick, and nothing is clicked" },
          { text: "If the user picks first, by hand, no click is made" },
        ],
      },
    },
  ],
};
