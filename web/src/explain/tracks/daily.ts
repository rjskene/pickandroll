// The daily automation track (#286): nine steps on the hour line, Central time. The whole day
// first under one sweeping clock, then the day one gate at a time: the sign-in check, the daily
// chain, the watchdog and its host, the execute time and one entry's day, the morning pass, the
// late pass, the evening build and the evening pass with its hard stop.
import type { Track } from "../types";

export const daily: Track = {
  id: "daily",
  title: "Daily play",
  short: "Daily",
  lede: "Central time. The armed public leagues run from a VM; the pinned private league (31822) gets suggestions only.",
  labels: ["The day", "Sign-in", "Daily", "Watchdog", "Execute", "Morning pass", "Late pass", "Evening build", "Evening pass"],
  hours: [null, 4.83, 5, 6.75, 9, 9.25, 15, 21, 22.67],
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
      example: {
        title: "A weekday as the logs saw it",
        lead: [{ text: "The armed public leagues and the pinned private league (31822); the counts are made up" }],
        table: {
          head: ["Time", "routine", "what it did"],
          rows: [
            ["04:50", "sign-in", "both sites signed in"],
            ["05:00–05:26", "daily", "exports, refresh, solve, lineups; four entries queued"],
            ["06:45", "watchdog", "marker, API and copy stamp all fresh"],
            ["09:15", "morning pass", "three claims placed, one page skipped"],
            ["15:00", "late pass", "lineups set before the 18:00 tip-off; one IL move"],
            ["21:00–21:12", "evening build", "solved again; two new entries queued"],
            ["22:40", "evening pass", "two claims placed, done by 22:47"],
          ],
        },
        read: [{ text: "Every line is one routine's row in the day's marker or a league's day log" }],
      },
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
      example: {
        title: "A morning with the projection source signed out",
        lead: [{ text: "The headed browser opens both sites' own pages at 04:50" }],
        table: {
          head: ["Time", "check", "result"],
          rows: [
            ["04:50", "Yahoo: the My Team page", "found: signed in"],
            ["04:50", "projections: the export link", "missing: a failed step"],
            ["04:51", "the alert", "names the one command the user runs on the Mac"],
            ["05:00", "the daily", "the API steps run; the browser steps wait for the sign-in"],
          ],
        },
        read: [{ text: "The user signs in through that command; no session types a password" }],
      },
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
      example: {
        title: "One day's marker, a line per step",
        lead: [{ text: "The window is 05:00 to 06:20; the times here are made up" }],
        table: {
          head: ["Step", "at", "result"],
          rows: [
            ["exports", "05:00", "ok"],
            ["private league's pages", "05:03", "ok, read-only"],
            ["public refresh", "05:04", "ok; one league retried at 05:31"],
            ["moves solve", "05:36", "ok; a decision-log entry per league"],
            ["Start Active Players", "05:41", "pressed where due"],
            ["lineups", "05:43", "today and tomorrow set"],
            ["queue", "05:47", "four entries"],
            ["digest", "05:49", "posted"],
          ],
        },
        read: [{ text: "A failed line posts an alert, and the watchdog reads this marker at 06:45" }],
      },
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
      example: {
        title: "06:45 on a good morning and on a bad one",
        lead: [{ text: "Three checks, read at 06:45 Central" }],
        table: {
          head: ["Check", "a good morning", "a bad morning"],
          rows: [
            ["today's marker", "eight steps, none failed", "the refresh failed"],
            ["the API", "answers", "answers"],
            ["the copy stamp", "03:31 today", "03:30 yesterday"],
            ["the verdict", "silent", "an alert, and a line on the ops issue"],
          ],
        },
        read: [{ text: "A stale stamp means last night's copy of the data folder to the Mac did not run" }],
      },
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
          formula: "executes-at",
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
      example: {
        title: "Three entries on one morning, execute time 09:00",
        lead: [
          {
            text: "An entry executes at the later of an hour after queueing and the day's execute time",
            sub: ["A to F are players: add A, drop B is one entry"],
          },
        ],
        table: {
          head: ["Entry", "queued", "an hour on", "executes at", "taken by"],
          rows: [
            ["add A, drop B", "05:40", "06:40", "09:00", "the 09:15 pass"],
            ["add C, drop D", "08:30", "09:30", "09:30", "the 15:00 late pass"],
            ["add E, drop F", "05:40", "06:40", "struck at 07:30", "nobody: no claim"],
          ],
        },
        read: [{ text: "At 09:15 the second entry is not due yet; the late pass finds it due" }],
      },
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
      example: {
        title: "The page check on one entry",
        lead: [{ text: "Add Player A, drop Player B, bid $6, in a league set to live" }],
        table: {
          head: ["Check", "the page and the log say", "passes"],
          rows: [
            ["the mode", "live, the live guard passed", "yes"],
            ["not struck", "no strike since 05:40", "yes"],
            ["Player A available", "the claim form for this league and team", "yes"],
            ["Player B droppable", "on my roster, not protected", "yes"],
            ["no claim pending", "none on Player A", "yes"],
            ["adds left", "2 of 4 used this week", "yes"],
          ],
        },
        read: [
          { text: "Live places the claim at $6; a dry run logs that same claim and submits nothing" },
          { text: "One mismatch and the entry is logged and skipped, never forced" },
        ],
      },
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
      example: {
        title: "15:00 in one league",
        lead: [{ text: "One armed public league; the players and times are made up" }],
        table: {
          head: ["Job", "what it did"],
          rows: [
            ["lineups", "today's starters set before the 18:00 tip-off; Player C, out, to the bench"],
            ["moves", "the entry queued at 08:30, due since 09:30: claimed at $2"],
            ["IL", "Player D, out, to the open IL slot"],
            ["Start Active Players", "pressed after the roster change"],
          ],
        },
        read: [{ text: "A player whose game has begun keeps his slot: his group is skipped whole" }],
      },
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
      example: {
        title: "The morning's queue and the evening's rebuild",
        lead: [{ text: "The 21:00 build reads Yahoo again and solves again; the queue is rebuilt, not replaced" }],
        table: {
          head: ["Entry", "by evening", "after the rebuild"],
          rows: [
            ["add A, drop B", "claimed at 09:15", "kept: executed"],
            ["add C, drop D", "struck by the user", "kept: struck"],
            ["add E, drop F", "queued, not yet due", "parked: superseded"],
            ["add G, drop H", "—", "new: queued at 21:08"],
          ],
        },
        read: [{ text: "A veto holds overnight: the rebuild keeps struck and executed entries by id" }],
      },
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
      example: {
        title: "A weekday evening and a Sunday evening",
        lead: [{ text: "Sunday's entries wait for 22:30, so their claims clear on Monday, in the new week" }],
        table: {
          head: ["Day", "execute time", "the 22:40 pass", "from 22:58"],
          rows: [
            ["weekday", "09:00, the user's own", "claims what is still due", "opens nothing"],
            ["Sunday", "22:30", "claims the day's entries", "opens nothing"],
          ],
        },
        read: [{ text: "A pass still running at 22:58 ends where it is: the queue's day ends at 23:00" }],
      },
    },
  ],
};
