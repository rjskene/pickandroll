// The draft track (#284): nine steps, from the stat line to the room. This file carries the
// first step as the track's lede until #284 lands the nine.
import type { Track } from "../types";

export const draft: Track = {
  id: "draft",
  title: "Draft",
  lede: "every pick is the first move of a plan for all my remaining picks, re-solved after each pick. The strip is the pipeline.",
  labels: ["Projections", "Pool & z", "Survival", "Objective", "Plan", "Price → pick", "Solve ahead", "Keepers", "Yahoo room"],
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
  ],
};
