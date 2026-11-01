// The daily automation track (#286): nine steps on the hour line, Central time. The whole day
// first under one sweeping clock, then the day one gate at a time: the sign-in check, the daily
// chain, the watchdog and its host, the execute time and one entry's day, the morning pass, the
// late pass, the evening build and the evening pass with its hard stop.
import type { Track } from "../types";

export const daily: Track = {
  id: "daily",
  title: "Daily play",
  lede: "Central time: the armed public leagues run themselves from a VM; the pinned private league (31822) gets suggestions only. The strip is the day.",
  labels: ["the day", "04:50 sign-in", "05:00 daily", "06:45 watchdog", "09:00 execute", "09:15 morning", "15:00 late", "21:00 build", "22:40 pass"],
  hours: [0, 4.83, 5, 6.75, 9, 9.25, 15, 21, 22.67],
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
    {
      id: "signin",
      title: "Check both sign-ins before the day starts",
      kicker: "04:50 · the sign-in check",
      figure: "signin-check",
      bullets: [
        {
          text: "Ten minutes before the daily, the headed browser opens each site's own page",
          sub: [
            "Yahoo: the My Team page, never a toolbar link that reads \"Sign in\" either way",
            "the projection source: its export link present",
          ],
        },
        {
          text: "Either site out: a failed step and an alert",
          sub: [
            "the alert names the one command the user runs on the Mac to sign the VM's browser in again",
            "the day's API steps still run; the browser steps wait for the sign-in",
          ],
        },
        { text: "No session ever handles a credential: the sign-in is the user's own" },
      ],
      source: ["routine/routines.py · signin", "docs/OPS.md · the re-sign-in", "the routines' skill files · the My Team rule"],
    },
    {
      id: "daily",
      title: "Build the day: export, refresh, solve, queue",
      kicker: "05:00 · the daily chain",
      figure: "daily-flow",
      bullets: [
        {
          text: "Window 05:00 to 06:20; a timer that fires late (a reboot, a busy box) is refused",
          sub: ["each step writes its own line to the day's marker; a failed step posts an alert"],
        },
        {
          text: "The chain, in order",
          sub: [
            "the exports through the signed-in browser; the private league's pages opened read-only",
            "every public league refreshed from Yahoo, paced, with a retry pass before 05:45",
            "the moves solve per league with its decision-log entry; Start Active Players where due",
            "lineups for today and tomorrow; the [queue] from the armed leagues' sets; the digest posted",
          ],
        },
        {
          text: "Mondays: a 06:00 recorder follows the daily",
          sub: [
            "last week recorded, the scorecard, the hill-climb's verdict and at most one change",
            "then every public league re-solved and the week's first queue under the new setting",
          ],
        },
      ],
      source: ["routine/routines.py · daily, monday, WINDOWS", "docs/AUTOPILOT.md · the weekly loop"],
    },
    {
      id: "watchdog",
      title: "The watchdog, and the host it watches",
      kicker: "06:45 · the watchdog and the host",
      figure: "host-watchdog",
      bullets: [
        {
          text: "The routines run on the VM as user timers that keep their Central times",
          sub: [
            "the browser is headed on a virtual display, with the extension and the user's own sign-in",
            "the API is a local service that restarts itself; the dashboard on the private network only",
          ],
        },
        {
          text: "The watchdog checks three things at 06:45",
          sub: [
            "today's daily marker present, with no failed step",
            "the API answering",
            "the nightly copy's stamp fresh: the VM's data folder to the Mac at 03:30, never a delete",
          ],
        },
        { text: "Anything else posts an alert and a line on the ops issue" },
      ],
      source: ["ops/vm · the timers, watchdog.sh", "docs/OPS.md"],
    },
    {
      id: "execute",
      title: "The veto window closes at the execute time",
      kicker: "09:00 · the execute time",
      figure: "entry-day",
      bullets: [
        {
          text: "A build reads, never solves",
          sub: [
            "each armed league's last moves entry of the day, the protected players, the breakout flags",
            "every available player's status and clear date, my budget, my recent drops, the adds left",
          ],
        },
        {
          text: "An entry executes at the later of two times",
          sub: [
            "an hour after it was queued: the [veto-window|veto window]",
            "the day's [execute-time|execute time]: 07:00 Central by default; the user's own is 09:00",
          ],
        },
        {
          text: "Until then the user can [strike] the entry, or its bid alone, from the Queue screen",
          sub: ["a struck bid stands as a $0 claim; a struck entry makes no claim and stays struck by id"],
        },
        { text: "The pinned private league (31822): its set is listed as suggestions to make by hand" },
        { text: "Press play, or strike the entry, and watch each gate open or close as the clock passes it" },
      ],
      source: ["season/autopilot.py · executes_at, due, effective_bid", "docs/AUTOPILOT.md · the queue"],
    },
    {
      id: "morning",
      title: "The morning pass: open the page, check it, then act",
      kicker: "09:15 · the morning pass",
      figure: "executor-modes",
      bullets: [
        { text: "Window 07:45 to 14:30; the timer at 09:15, after the user's execute time" },
        {
          text: "Each due entry's add page is opened with the moves fragment; the extension re-reads it",
          sub: [
            "the page check: add available, drop on the roster and not protected, under the cap, not struck",
            "[dry-run|dry run]: logs what it would claim; live: places the claim at the queued bid",
            "a page that does not match is logged and skipped, never forced; one live run per league per pass",
          ],
        },
        {
          text: "The mode is per league, set by the user's click: off, dry run, live",
          sub: [
            "live is refused until the [live-guard|live guard] passes, and read again on every live run",
            "a STOP file halts every executor at once; the private league is always off and refuses the switch",
          ],
        },
        { text: "Every click goes to the league's day log with the page before and after; then Start Active Players where due" },
      ],
      source: ["routine/routines.py · morning", "docs/AUTOPILOT.md · the modes, the live guard, STOP, the page check"],
    },
    {
      id: "late",
      title: "The late pass: lineups before the first tip-off",
      kicker: "15:00 · the late pass",
      figure: "late-pass",
      bullets: [
        {
          text: "Window 15:00 to 20:30; four jobs, in order",
          sub: [
            "the lineup for today, now with the day's news, before the first tip-off",
            "the claims still due",
            "IL moves: a player out to an open IL slot, a returning one back",
            "Start Active Players after any roster change",
          ],
        },
        {
          text: "Start Active Players is Yahoo's own baseline; the lineup executor sets its days on top",
          sub: [
            "pressed at the week's start, after a roster change or IL move, after a lineup set for a later day",
            "a later day's only: Yahoo's button runs today at once and could undo a swap set for today",
            "no press after an add: in the live leagues an add is a claim until Yahoo's overnight run",
          ],
        },
        { text: "A player whose game has begun is never touched: his group is skipped whole; held slots never" },
      ],
      source: ["routine/routines.py · late", "docs/AUTOPILOT.md · the steps, the live run, §2 the reasons (lineup_set)"],
    },
    {
      id: "build",
      title: "Build again on the day's information",
      kicker: "21:00 · the evening build",
      figure: "evening-build",
      bullets: [
        {
          text: "Window 21:00 to 21:30: the morning's chain without the lineups",
          sub: ["fresh exports by 21:15, every public league re-read from Yahoo and re-solved, the queue rebuilt"],
        },
        {
          text: "A rebuild keeps struck and executed entries by id, so a morning veto holds",
          sub: ["an entry the evening's solve no longer recommends is parked as superseded, never deleted"],
        },
      ],
      source: ["routine/routines.py · evening_build", "season/autopilot.py · merge, SUPERSEDED"],
    },
    {
      id: "pass",
      title: "The evening pass, and the day is done",
      kicker: "22:40 · the evening pass",
      figure: "evening-pass",
      bullets: [
        { text: "The remaining claims on the evening's solve, with the same page check and one live run per league" },
        {
          text: "A hard stop at 22:58: from then it opens nothing; the queue's day ends at 23:00",
          sub: ["a run past the stop ends where it is"],
        },
        {
          text: "Sunday: an execute time of its own, 22:30, so Sunday's claims wait for the evening pass",
          sub: ["a Sunday claim clears on Monday, against the new week; then the adds-left report for the new week"],
        },
        { text: "At 03:30 the VM's data folder is copied to the Mac; the day begins again at 04:50" },
      ],
      source: ["routine/routines.py · evening_pass, EVENING_HARD_STOP", "season/autopilot.py · day_time", "docs/AUTOPILOT.md · the Sunday turn"],
    },
  ],
};
