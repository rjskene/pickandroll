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
        { text: "A category's variance is a fitted dispersion times its weekly total" },
        {
          text: "The odds of winning a category: my lead over the opponent, measured in our combined spread",
          formula: "category-odds",
          sub: ["the matchup's week so far is added to both totals first"],
        },
        { text: "[ecw|Expected categories won] is the sum of the nine" },
      ],
      source: ["docs/ADD_DROP.md · the weekly projection", "api/season_week.py"],
      example: {
        title: "One matchup week: four of the nine",
        lead: [
          {
            text: "My finals and the opponent's: the week so far plus the projected rest",
            sub: ["the spread from each category's fitted dispersion: points 3.17, rebounds 1.34"],
          },
        ],
        table: {
          head: ["Cat", "mine", "theirs", "my lead", "spread", "P(win)"],
          num: [1, 2, 3, 4, 5],
          rows: [
            ["PTS", "610", "570", "40", "61.2", "0.74"],
            ["REB", "260", "285", "−25", "27.0", "0.18"],
            ["AST", "150", "140", "10", "19.2", "0.70"],
            ["STL", "40", "42", "−2", "9.4", "0.42"],
          ],
        },
        read: [
          { text: "A 40-point lead is 0.65 of the combined spread: 0.74 to win points" },
          { text: "These four add to 2.04 expected wins; the nine add up the same way" },
        ],
      },
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
      example: {
        title: "Three candidate moves on both horizons",
        lead: [
          {
            text: "Gains in expected categories won; the season in value units",
            sub: ["this week: against the named opponent; three weeks: against the field"],
          },
        ],
        table: {
          head: ["Move", "this week", "three weeks", "season"],
          num: [1, 2, 3],
          rows: [
            ["add Player A, drop Player B", "+0.31", "+0.12", "+4.0"],
            ["add Player C, drop Player D", "+0.05", "+0.40", "+9.5"],
            ["add Player E, drop Player B", "+0.42", "−0.10", "−6.0"],
          ],
        },
        read: [
          { text: "On this week alone Player E for Player B wins; on three weeks, Player C for Player D" },
          { text: "Player E for Player B costs the season: the guard holds that set back and says so" },
        ],
      },
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
      example: {
        title: "Five players on my roster, one add on offer",
        lead: [
          {
            text: "The best available add is worth 0.3 a game; the floor is 0.5 here, zero by default",
            sub: ["values: rest-of-season z per game, where zero is the pool's average"],
          },
        ],
        table: {
          head: ["Player", "value", "status", "verdict"],
          num: [1],
          rows: [
            ["Player A", "2.4", "out 12 days", "protected: to an open IL slot"],
            ["Player B", "0.1", "healthy", "protected: 0.1 plus the floor beats 0.3"],
            ["Player C", "−0.1", "out 4 days", "benched: kept, back within a week"],
            ["Player D", "−0.4", "healthy", "can go: −0.4 plus the floor is under 0.3"],
            ["Player E", "1.0", "out for the season", "can go: never protected"],
          ],
        },
        read: [
          { text: "Player A stays though out twelve days: a three-week horizon alone would drop him" },
          { text: "With the floor at zero, neither Player B nor Player C would be kept" },
        ],
      },
    },
    {
      id: "bids-trades",
      title: "Size the bid, show the odds, score the trade",
      kicker: "bids, claims, trades",
      figure: "bids-trades",
      bullets: [
        {
          text: "Public leagues: [faab|FAAB], continuous waivers of two days, four adds a week",
          formula: "bid",
          sub: [
            "a cleared free agent is added at once for $0; a claim lands at Yahoo's overnight run",
            "the bid: the gain in multiples of the typical gain, at least $1; doubled or tripled for a flag",
            "clamped to the budget left; [queue|queued] with its reason, and a [strike|struck] bid is a $0 claim",
          ],
        },
        {
          text: "The pinned private league (31822): free agents, one-day [priority] waivers, five adds a week",
          formula: "claim-odds",
          sub: [
            "an add before a player's game plays that night",
            "no bid: the odds that no team ahead in priority claims him, at an assumed rate, shown as assumed",
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
      example: {
        title: "A claim in a public league, and one in the private league",
        lead: [
          {
            text: "Public: a move worth 0.42 when the typical gain is 0.15, with a breakout flag",
            sub: ["$40 of budget left; the pinned private league (31822): 4th in waiver priority"],
          },
        ],
        table: {
          head: ["Line", "public league", "private league"],
          rows: [
            ["the gain in typicals", "0.42 over 0.15 is 2.8: rounds to 3", "no bid"],
            ["the flag", "a breakout: doubled to $6", "—"],
            ["the budget", "$40 left: $6 stands", "—"],
            ["the queue's reason", "$6: gain 3x the typical, x2 for a breakout flag", "—"],
            ["the claim's odds", "the highest bid wins", "three teams ahead at 0.3 each: 0.34, assumed"],
          ],
        },
        read: [
          { text: "A struck bid stands as a $0 claim; a cleared free agent is added at once for $0" },
          { text: "A trade is scored the same way, both horizons and the season beside; nothing sends it" },
        ],
      },
    },
  ],
};
