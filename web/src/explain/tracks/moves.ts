// The moves and trades track (#285): four steps, from the weekly odds to bids, claims and
// trades. Every card is bullets: key ideas with their sub-ideas, two levels, no paragraphs
// (the user's rule, #282). Sources are docs/ADD_DROP.md, docs/AUTOPILOT.md, api/season_week.py,
// api/season_queue.py and the keep rule in season/moves.py.
import type { Track } from "../types";

export const moves: Track = {
  id: "moves",
  title: "Moves & trades",
  lede: "which add and drop raises the categories I am expected to win, this week and over three, without costing the season.",
  labels: ["Weekly odds", "Horizons", "Keep rule", "Bids & trades"],
  steps: [
    {
      id: "weekly-odds",
      title: "Project the week on the slots I can start",
      kicker: "the weekly odds",
      figure: "weekly-odds",
      bullets: [
        {
          text: "Each player's per-game rates times his team's games in the week, on the ten startable slots",
          sub: [
            "rates: the source's rest-of-season line, Yahoo's seven-day projection, or a [blend]",
            "each day the players with a game fill the slots exactly, best first",
          ],
        },
        { text: "A category's spread is a fitted per-game dispersion times its total" },
        { text: "The odds of winning a category: Φ(Δ / √(σ₁² + σ₂²)), the matchup's week so far added" },
        { text: "[ecw|Expected categories won] is the sum of the nine" },
      ],
      source: ["docs/ADD_DROP.md · the weekly projection", "api/season_week.py"],
    },
    {
      id: "horizons",
      title: "Rank moves on two horizons, show the season beside",
      kicker: "horizons and the search",
      figure: "horizons",
      bullets: [
        {
          text: "This week: the rest of the current week against the named opponent, the week so far included",
          sub: ["its first day is today, or tomorrow once today's games have begun"],
        },
        {
          text: "Three weeks: weeks 2 to 4 against the field",
          sub: ["the mean over the other teams of the per-opponent odds on their projected rosters"],
        },
        {
          text: "[season-first|Season first]: the rest of the season sits beside both, in value units",
          sub: ["every move shows both gains, whichever horizon chose it"],
        },
        {
          text: "The search tries every (add, drop) pair exactly, on the same evaluator as the Matchup card",
          sub: ["the set under the weekly add limit: greedy swaps, then a replacement pass", "so the UI says recommended, never a stronger word"],
        },
        {
          text: "A player I dropped within the league's waiver days is never added back the same stretch",
          sub: ["a re-add would be a claim on my own drop"],
        },
      ],
      source: ["docs/ADD_DROP.md · horizons, the search", "api/season_week.py · first_day", "api/season_queue.py · dropped_recently"],
    },
    {
      id: "keep-rule",
      title: "Never drop a great player for one week",
      kicker: "the keep rule and the season guard",
      figure: "keep-rule",
      bullets: [
        { text: "A three-week horizon values a player out for three weeks at about nothing, so the keep rule stands outside it" },
        {
          text: "[protected|Protected]: all three, on his rest-of-season line; then never a drop on any horizon",
          sub: [
            "net positive: above the pool's average",
            "not beaten by the best available add by the [floor|protection floor]",
            "back this season; out, he goes to an open IL slot instead",
          ],
        },
        {
          text: "Benched: not beaten by the floor, not net positive, back within seven days",
          sub: ["a replacement-level player out a few days is streamed like any other"],
        },
        { text: "Yahoo's can't-cut list protects on its own" },
        {
          text: "The [guard|season guard] holds every recommended set to a rest of the season of zero or more",
          sub: ["it says what it held back, and what the guarded set forgoes"],
        },
      ],
      source: ["docs/ADD_DROP.md · the keep rule, the season guard", "season/moves.py · the keep rule"],
    },
    {
      id: "bids-trades",
      title: "Size the bid, show the odds, score the trade",
      kicker: "bids, claims, trades",
      figure: "bids-trades",
      bullets: [
        {
          text: "Public leagues: [faab|FAAB], continuous waivers of two days, four adds a week",
          sub: [
            "a cleared free agent is added at once for $0; a claim lands at Yahoo's overnight run",
            "the bid: max(1, round(gain / typical)), doubled for a breakout flag, tripled for a strong one",
            "clamped to the budget left; [queue|queued] with its reason, and a [strike|struck] bid is a $0 claim",
          ],
        },
        {
          text: "The pinned private league (31822): free agents, one-day [priority] waivers, five adds a week",
          sub: [
            "an add before a player's game plays that night",
            "no bid: the claim's odds (1 − q)^(p − 1) with an assumed rival rate, shown as assumed",
            "suggestions only: every move there is the user's own",
          ],
        },
        {
          text: "A proposed trade is scored on both horizons with the season beside",
          sub: ["the least costly drop and the best fill named; the margin that makes it neutral reported", "nothing sends or accepts a trade"],
        },
        { text: "The hill-climb may tune the bid sizing within bounds" },
      ],
      source: ["docs/ADD_DROP.md · the two kinds of league, trades", "docs/AUTOPILOT.md · the bid rule", "api/season_queue.py"],
    },
  ],
};
