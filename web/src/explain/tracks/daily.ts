// The daily automation track (#286): nine steps on the hour line. This file carries the first
// step, the whole day on one clock, as the track's lede until #286 lands the nine.
import type { Track } from "../types";

export const daily: Track = {
  id: "daily",
  title: "Daily play",
  lede: "Central time: the armed public leagues run themselves from a VM; the pinned private league (31822) gets suggestions only. The strip is the day.",
  labels: ["the day", "04:50 sign-in", "05:00 daily", "06:45 watchdog", "09:00 execute", "09:15 morning", "15:00 late", "21:00 build", "22:40 pass"],
  steps: [
    {
      id: "the-day",
      title: "The day's gates, under a sweeping clock",
      kicker: "00:00",
      figure: "day-line",
      wide: true,
      bullets: [
        {
          text: "Before the steps, the whole day at once: every action on its own lane",
          sub: [
            "lit while its window or its gate allows it, hatched while it may not, amber once it ran",
            "the clock sweeps; what lies ahead is dimmed",
          ],
        },
        {
          text: "Switch the day to watch the gates move",
          sub: [
            "Sunday: the 22:30 [execute-time|execute time] holds the day's claims for the evening pass",
            "Monday: the recorder's window opens at 06:00",
            "a draft room on the server: the sessions' rule closes the passes and the restarts",
          ],
        },
        { text: "The steps that follow take the day one gate at a time" },
      ],
      source: ["routine/routines.py · the windows and the hard stop", "season/autopilot.py · executes_at, due", "docs/AUTOPILOT.md"],
    },
  ],
};
