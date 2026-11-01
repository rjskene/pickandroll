// The shared day line (#283, #286): the day's actions as lanes on one 24-hour axis, Central
// time; a weekday, a Sunday or a Monday, with or without a draft room on the server. The
// windows, the execute time, the veto rule, the tip-off lock, the hard stop and the Sunday
// turn are the routines' (routine/routines.py, season/autopilot.py, docs/AUTOPILOT.md); the
// run lengths, the 05:40 entry and the 18:00 tip-off are an example day. The last lane is the
// sessions' working agreement, not a gate in the code. No React, so the test runs under Node.
import { M, hhmm } from "./lane.ts";
import type { Lane, Seg } from "./lane.ts";

export type Day = "week" | "sun" | "mon";

type Win = [number, number];

export const WIN: Record<string, Win> = {
  daily: [M(5), M(6, 20)],
  morning: [M(7, 45), M(14, 30)],
  late: [M(15), M(20, 30)],
  build: [M(21), M(21, 30)],
  evening: [M(22, 40), M(22, 58)],
  monday: [M(6), M(12)],
};

export const DAY_END = 1440;
export const DAY_SECONDS = 48;

const refuses = "a routine outside its window refuses to run";

/** A routine with a window: blocked before it opens, running then open inside, blocked after. */
function routine(w: Win, room: boolean, runEnd: number, runL: string, openL: string, pass: boolean, closedL?: string): Seg[] {
  const inside: Seg[] =
    room && pass
      ? [{ a: w[0], b: w[1], k: "block", l: "held: a draft room is on the server, so no pass runs (the sessions' rule)" }]
      : [
          { a: w[0], b: runEnd, k: "run", l: runL },
          { a: runEnd, b: w[1], k: "open", l: openL },
        ];
  return [
    { a: 0, b: w[0], k: "block", l: `before its window opens at ${hhmm(w[0])}: ${refuses}` },
    ...inside,
    { a: w[1], b: DAY_END, k: "block", l: closedL ?? `its window closed at ${hhmm(w[1])}: ${refuses}` },
  ];
}

/** A timer that fires once: idle, a short run, then ran. */
function point(at: number, runL: string, afterL: string, waitL: string): Seg[] {
  return [
    { a: 0, b: at, k: "idle", l: waitL },
    { a: at, b: at + 3, k: "run", l: runL },
    { a: at + 3, b: DAY_END, k: "after", l: afterL },
  ];
}

/** The day's lanes for one kind of day, with or without a draft room on the server. */
export function dayLanes(day: Day, room: boolean): Lane[] {
  const sun = day === "sun";
  const mon = day === "mon";
  const exec = sun ? M(22, 30) : M(9);
  const claim = sun ? M(22, 40) : M(9, 15);
  const wins = [WIN.daily, WIN.morning, WIN.late, WIN.build, WIN.evening].concat(mon ? [WIN.monday] : []).sort((a, b) => a[0] - b[0]);
  const guard: Seg[] = [];
  if (room) {
    guard.push({ a: 0, b: DAY_END, k: "block", l: "a draft room is on the server: no pull, checkout, source edit or API restart, and no pass (the sessions' rule: a reload drops the in-memory sessions, and a pull is a source edit)" });
  } else {
    // Windows that overlap (Monday's recorder over the daily and the morning) are one closed span.
    const spans: Win[] = [];
    for (const w of wins) {
      const prev = spans[spans.length - 1];
      if (prev && w[0] <= prev[1]) prev[1] = Math.max(prev[1], w[1]);
      else spans.push([w[0], w[1]]);
    }
    let last = 0;
    for (const w of spans) {
      if (w[0] > last) guard.push({ a: last, b: w[0], k: "open", l: "clear: no routine window is open" });
      guard.push({ a: w[0], b: w[1], k: "block", l: `inside the ${hhmm(w[0])} to ${hhmm(w[1])} window: no pull, checkout, source edit or API restart (the sessions' rule, not a code gate)` });
      last = w[1];
    }
    guard.push({ a: last, b: DAY_END, k: "open", l: "clear: no routine window is open" });
  }
  return [
    { name: "nightly copy", sub: "03:30 · after the cut-over", segs: point(M(3, 30), "the VM's data folder copied to the Mac: adds and updates, never deletes", "copied at 03:30; the watchdog checks the stamp at 06:45", "waits for its 03:30 timer") },
    { name: "sign-in check", sub: "04:50 · both sites", segs: point(M(4, 50), "each site's own page opened: Yahoo's My Team, the projection source's export link", "both signed in; either out would post an alert naming the one command the user runs on the Mac", "waits for its 04:50 timer") },
    { name: "daily chain", sub: "window 05:00 to 06:20", segs: routine(WIN.daily, room, M(5, 30), "exports → the private league's pages → every public league refreshed, paced → the solves → Start Active → lineups today and tomorrow → the queue → the digest", "window open to 06:20: a retry pass before 05:45 for a league the refresh missed", false) },
    { name: "watchdog", sub: "06:45", segs: point(M(6, 45), "today's daily marker with no failed step, the API answering, the copy's stamp fresh", "checked at 06:45; anything else posts an alert and a line on the ops issue", "waits for 06:45") },
    { name: "Monday recorder", sub: "window 06:00 to 12:00, Mondays", segs: mon ? routine(WIN.monday, room, M(6, 20), "last week recorded; the scorecard, projected against actual; the hill-climb's verdict and at most one change; the week's first queue under the new setting", "window open to 12:00", false) : [{ a: 0, b: DAY_END, k: "block", l: "not a Monday: the recorder runs once a week" }] },
    {
      name: "queue entry · queued 05:40",
      sub: "due at the later of 06:40 and the execute time",
      marks: [{ at: exec, k: "tick" }],
      segs: [
        { a: 0, b: M(5, 40), k: "idle", l: "not queued yet: the daily builds the queue from the armed leagues' recommended sets" },
        { a: M(5, 40), b: M(6, 40), k: "block", l: "veto window: not before an hour after it was queued (06:40); the user may strike the entry, or its bid alone" },
        { a: M(6, 40), b: exec, k: "block", l: `veto window: not before the day's execute time (${hhmm(exec)}${sun ? ", Sunday's own: a Sunday claim clears on Monday against the new week" : ", the user's; 07:00 by default"}); the user may strike the entry, or its bid alone` },
        { a: exec, b: claim, k: "open", l: `due since ${hhmm(exec)}: the next pass takes it` },
        { a: claim, b: DAY_END, k: "done", l: `claimed at ${hhmm(claim)}: the page check passed and the claim was placed; it lands at Yahoo's overnight run, and a rebuild keeps an executed entry by id` },
      ],
    },
    { name: "morning pass", sub: "window 07:45 to 14:30 · timer 09:15", segs: routine(WIN.morning, room, M(9, 25), sun ? "nothing due: Sunday's entries wait for the 22:30 execute time; Start Active Players where due" : "each due entry's add page opened with the moves fragment, the claim form checked, the claim placed (live) or logged (dry run); then Start Active Players where due", "window open to 14:30: a pass run by hand still may", true) },
    { name: "late pass", sub: "window 15:00 to 20:30", segs: routine(WIN.late, room, M(15, 10), "lineups for today before the first tip-off, the moves still due, IL moves, Start Active Players after a roster change", "window open to 20:30", true) },
    { name: "evening build", sub: "window 21:00 to 21:30", segs: routine(WIN.build, room, M(21, 15), "exports again, every public league re-read and re-solved, the queue rebuilt on the day's information (struck and executed entries kept by id)", "window open to 21:30", false) },
    { name: "evening pass", sub: "22:40 · hard stop 22:58", marks: [{ at: M(22, 58), k: "stop" }], segs: routine(WIN.evening, room, M(22, 50), sun ? "Sunday's claims, due since 22:30, placed; then the adds-left report for the new week" : "the remaining due claims, one live run a league a pass", "open to the hard stop", true, "from 22:58 it opens nothing: the queue's day ends at 23:00") },
    {
      name: "lineup move · tip-off 18:00",
      sub: "no veto window: reversible until his tip-off",
      marks: [{ at: M(18), k: "tick" }],
      segs: [
        { a: 0, b: M(18), k: "open", l: "allowed: a lineup is reversible until tip-off, so the passes set today and tomorrow without a veto window" },
        { a: M(18), b: DAY_END, k: "block", l: "his game has begun: a step touching him is skipped and held slots are never touched; the team page's day is tomorrow, and the rest-of-week projection's first day flips with it (19:00 ET)" },
      ],
    },
    { name: "pull · checkout · source edit · API restart", sub: "the sessions' working agreement, not a code gate", segs: guard },
  ];
}

/** The axis ticks: every three hours, every six on a phone. */
export function dayTicks(phone: boolean): { v: number; l: string }[] {
  const out: { v: number; l: string }[] = [];
  for (let h = 0; h <= 24; h += phone ? 6 : 3) out.push({ v: h * 60, l: `${String(h).padStart(2, "0")}:00` });
  return out;
}

/** The clock's reading on the day line. */
export function dayNow(t: number, day: Day): string {
  return hhmm(t) + (day === "sun" ? " Sun" : day === "mon" ? " Mon" : "");
}
