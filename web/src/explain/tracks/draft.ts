// The draft track (#284): nine steps, from the stat line to the room. Every card is bullets:
// key ideas with their sub-ideas, two levels, no paragraphs (the user's rule, #282). Sources
// are docs/DESIGN.md, docs/KEEPERS.md, docs/YAHOO_SYNC.md and the extension's constants.
import type { Track } from "../types";

export const draft: Track = {
  id: "draft",
  title: "Draft",
  lede: "every pick is the first move of a plan for all my remaining picks, re-solved after each pick. The strip is the pipeline.",
  labels: ["Projections", "Pool & z", "Survival", "Objective", "Plan", "Price → pick", "Solve ahead", "Keepers", "Yahoo room"],
  loop: { from: 8, to: 2, label: "after every pick in the room, back to the board: the plan is re-solved" },
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
    },
    {
      id: "pool",
      title: "Score every stat against the players who will be drafted",
      kicker: "the pool and z-scores",
      figure: "pool-bars",
      bullets: [
        {
          text: "[z-score|Z-scores] are taken against the [pool|draft pool]: the players who will actually be drafted",
          sub: [
            "found iteratively: score all, keep the top teams × roster by total, rescore; repeat until it settles",
            "counting categories: (x − mean) / spread, turnovers negated",
          ],
        },
        {
          text: "Percentages are scored as impact: makes − pool% × attempts",
          sub: ["impact adds linearly over a roster: a team's percentage is exact, never a mean of percentages"],
        },
        { text: "Example: 12 teams × 13 roster spots is a pool of 156" },
      ],
      source: ["docs/DESIGN.md · the pool and z-scores", "projections/zscores.py and optim/pool.py under src/"],
    },
    {
      id: "survival",
      title: "How likely is he still there at my next pick?",
      kicker: "survival",
      figure: "survival",
      bullets: [
        {
          text: "A value becomes a plan only through [survival], always read conditionally from the current pick",
          sub: ["S(k) / S(now): what counts is the chance he lasts from here, not from pick one"],
        },
        {
          text: "Three sources, best first",
          sub: [
            "the league's own record: [keeper-adp|keeper-adjusted ADP] and the share never drafted, blended at D/(D+1)",
            "a simulated table of 300 drafts when the league has no archive",
            "the [adp|ADP] formula 1 − Φ((k − ADP) / sd), with the league's ADP-bias shift, where a table has no row",
          ],
        },
        { text: "The record carries what the formula cannot: the players who are never drafted at all" },
      ],
      source: ["docs/DESIGN.md · survival", "availability/survival.py and availability/league.py under src/"],
    },
    {
      id: "objective",
      title: "Count the categories the roster is expected to win",
      kicker: "the objective",
      figure: "objective",
      bullets: [
        {
          text: "The roster is scored as [ecw|expected categories won]: max Σ Φ((T − μ) / σ) over the categories",
          sub: [
            "T is the roster's projected total; μ and σ the league's mean and spread of team totals, the [curve]",
            "fitted on 36,000 simulated teams, or on the league's own rosters blended toward that prior",
          ],
        },
        {
          text: "A category the board has made unwinnable has near-zero [marginal|marginal value], so the plan stops paying for it",
          sub: ["a punt can emerge; nobody chooses one"],
        },
        { text: "The solver carries Φ piecewise, with breakpoints at ±0.5σ, ±1.5σ and ±2.5σ" },
      ],
      source: ["docs/DESIGN.md · the objective", "optim/objective.py under src/"],
    },
    {
      id: "plan",
      title: "Plan every remaining pick, act on the first",
      kicker: "the plan",
      figure: "plan",
      bullets: [
        {
          text: "The [horizon-plan|rolling-horizon model] plans one player for each of my remaining picks",
          sub: [
            "each discounted by the chance he lasts to that pick: value = z × A[player, pick]",
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
    },
    {
      id: "price",
      title: "Price every candidate, show the recommendation and its ties",
      kicker: "the price, and the pick",
      figure: "price",
      bullets: [
        {
          text: "Each candidate is forced to be the first pick in turn; the objective lost is his [price] now",
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
    },
    {
      id: "keepers",
      title: "Keepers are picks already made",
      kicker: "keepers",
      figure: "keeper-snake",
      bullets: [
        {
          text: "A [keeper] is (team position, round, player); his overall pick follows from the draw",
          sub: ["example: rounds 7 and 13 from position 4 are overall 76 and 148"],
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
    },
  ],
};
