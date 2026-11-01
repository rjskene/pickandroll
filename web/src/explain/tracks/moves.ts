// The moves and trades track (#285): four steps. This file carries the first step as the
// track's lede until #285 lands the four.
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
  ],
};
