// The Demo's sample week (FLOOR PR 3, #460): Monday 16 to Sunday 22 November 2026, made up end
// to end. The leagues, their ids and the players are invented; nothing here is a real league, team
// or roster. The shapes are the real payloads' (the run reports, each day's queue, the leagues),
// and the week follows the approved mock-up: its routines at their timers, its steps and their
// lengths, its entries and their holds. The model reads it like the live payloads.

import type {
  QueueEntry,
  QueueLeague,
  QueuePayload,
  QueueReason,
  RoutinePass,
  RoutinePretipDay,
  RoutineRunLog,
  RoutineRunsPayload,
  RoutineStepLog,
  SeasonSummary,
} from "../api.ts";

export const DATES = ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21", "2026-11-22"];

/** The private league, then the public ones in a pass's order. */
export const PRIVATE = "900100";
export const PUBLIC = ["900101", "900102", "900103", "900104", "900105", "900106", "900107", "900108", "900109"];
const ALL = [PRIVATE, ...PUBLIC];

const PLAYERS = [
  "Ari Vance", "Bo Lindqvist", "Cal Okafor", "Dario Whitlock", "Eli Marchetti", "Finn Adebayo-Rhodes", "Gus Tamarind",
  "Hal Brightwater", "Ivo Castellane", "Jules Okonkwo", "Kip Ravensworth", "Lou Fairbanks", "Milo Sandoval", "Nico Brandt",
  "Otto Kessler", "Pax Harrow", "Quin Delacroix", "Rafe Ostrander", "Sol Achterberg", "Tad Winslow", "Uli Moravec",
  "Vic Holloway", "Wes Calloway", "Xan Petrakis", "Yuri Lindgren", "Zed Ashcombe", "Abe Quill", "Bram Ellery",
];
/** Player ids, from 7001, with their names as a queue's ``names`` carries them. */
export const NAMES: Record<string, string> = Object.fromEntries(PLAYERS.map((n, i) => [String(7001 + i), n]));
const id = (name: string): number => 7001 + PLAYERS.indexOf(name);

// ---------------------------------------------------------------- the clock (Central, -06:00)
/** ``day`` of the week (0 Monday) at ``minutes`` past Central midnight, as an ISO string. */
const at = (day: number, minutes: number): string => {
  const t = Date.parse(`${DATES[day]}T00:00:00-06:00`) + Math.round(minutes * 60_000);
  return new Date(t).toISOString();
};
const hm = (s: string): number => Number(s.slice(0, 2)) * 60 + Number(s.slice(3, 5));

// ---------------------------------------------------------------- the entries
type Slot = "morning" | "late" | "evening";
type Res = "claimed" | "failed" | "skipped" | "held";
interface Spec {
  day: number;
  slot: Slot;
  league: string;
  add: string;
  drop: string | null;
  bid: number;
  gain: number;
  res: Res;
  why?: string;
  /** Placed for an open spot after an IL move. */
  il?: boolean;
}
const S = (day: number, slot: Slot, league: string, add: string, drop: string | null, bid: number, gain: number, res: Res, why?: string, il?: boolean): Spec => ({
  day, slot, league, add, drop, bid, gain, res, why, il,
});
const [L1, L2, L3, L4, L5, L6, L7, L8, L9] = PUBLIC;

/** The week's entries: their day, the pass that executes them, and the outcome or the hold. */
const SPECS: Spec[] = [
  S(0, "morning", L2, "Ari Vance", null, 0, 0.31, "failed", "Yahoo stayed on the claim form: not placed"),
  S(0, "morning", L4, "Bo Lindqvist", null, 3, 0.62, "claimed"),
  S(0, "morning", L8, "Cal Okafor", "Dario Whitlock", 2, 0.44, "claimed"),
  S(0, "morning", L5, "Ari Vance", "Bo Lindqvist", 0, 0.08, "held", "below the noise floor"),
  S(0, "morning", L4, "Eli Marchetti", "Finn Adebayo-Rhodes", 0, 0.21, "held", "the add is a player this queue drops today or dropped within the waiver days"),
  S(0, "morning", L8, "Gus Tamarind", "Hal Brightwater", 2, 0.35, "held", "a later step of the week plan: queued at its day's build"),
  S(0, "evening", L1, "Ivo Castellane", "Bo Lindqvist", 4, 0.71, "claimed"),
  S(0, "evening", L3, "Jules Okonkwo", null, 4, 0.58, "claimed"),
  S(0, "evening", L7, "Kip Ravensworth", null, 4, 0.66, "skipped", "move dated Tue Nov 17, claim waits"),
  S(1, "morning", L1, "Cal Okafor", null, 10, 1.12, "claimed"),
  S(1, "morning", L1, "Lou Fairbanks", null, 0, 0.19, "claimed"),
  S(1, "morning", L1, "Milo Sandoval", "Nico Brandt", 0, 0.17, "held", "over the day's cap"),
  S(1, "morning", L2, "Otto Kessler", null, 0, 0.22, "claimed"),
  S(1, "morning", L3, "Pax Harrow", "Quin Delacroix", 2, 0.47, "claimed"),
  S(1, "morning", L7, "Kip Ravensworth", null, 4, 0.66, "claimed"),
  S(1, "morning", L8, "Ivo Castellane", null, 3, 0.52, "claimed"),
  S(1, "evening", L6, "Rafe Ostrander", "Ari Vance", 0, 0.26, "skipped", "a cleared player sits on IL: Yahoo refuses every claim until they leave it"),
  S(1, "evening", L6, "Pax Harrow", "Sol Achterberg", 1, 0.33, "held", "the drop is protected"),
  S(2, "morning", L1, "Jules Okonkwo", "Nico Brandt", 0, 0.2, "claimed"),
  S(2, "morning", L2, "Tad Winslow", "Bo Lindqvist", 0, 0.24, "claimed"),
  S(2, "morning", L3, "Milo Sandoval", null, 0, 0.18, "claimed"),
  S(2, "morning", L4, "Milo Sandoval", "Uli Moravec", 0, 0.12, "held", "below the noise floor"),
  S(2, "morning", L3, "Milo Sandoval", "Vic Holloway", 0, 0.15, "held", "a claim on the add is already placed"),
  S(2, "evening", L7, "Wes Calloway", null, 0, 0.23, "claimed", undefined, true),
  S(2, "evening", L7, "Ari Vance", null, 0, 0.2, "claimed"),
  S(2, "evening", L9, "Xan Petrakis", null, 0, 0.27, "claimed"),
  S(2, "evening", L9, "Yuri Lindgren", null, 2, 0.41, "skipped", "move dated Thu Nov 19, claim waits"),
  S(3, "morning", L2, "Ari Vance", null, 2, 0.43, "claimed"),
  S(3, "morning", L2, "Wes Calloway", "Zed Ashcombe", 1, 0.12, "held", "held for the week's reserve"),
  S(3, "morning", L3, "Abe Quill", "Bram Ellery", 2, 0.45, "claimed"),
  S(3, "morning", L3, "Eli Marchetti", null, 3, 0.5, "held", "no adds left this week"),
  S(3, "morning", L1, "Gus Tamarind", "Ivo Castellane", 5, 0.6, "held", "this week's adds are not fully read: the transactions reads do not reach its start"),
  S(3, "morning", L9, "Yuri Lindgren", null, 2, 0.41, "claimed"),
  S(3, "morning", L9, "Hal Brightwater", "Xan Petrakis", 1, 0.22, "held", "an earlier step of the week plan is not queued"),
  S(4, "morning", L1, "Finn Adebayo-Rhodes", "Ivo Castellane", 0, 0.24, "claimed"),
  S(4, "morning", L2, "Wes Calloway", "Zed Ashcombe", 1, 0.12, "claimed"),
  S(4, "morning", L6, "Dario Whitlock", "Eli Marchetti", 3, 0.68, "claimed"),
  S(4, "morning", L4, "Nico Brandt", "Quin Delacroix", 1, 0.09, "held", "below the noise floor"),
  S(4, "morning", L1, "Uli Moravec", "Lou Fairbanks", 2, 0.48, "held", "the add is a player this queue drops today or dropped within the waiver days"),
  S(4, "morning", L5, "Vic Holloway", "Ari Vance", 1, 0.3, "held", "its drop is on a claim already placed"),
  S(5, "morning", L5, "Xan Petrakis", "Milo Sandoval", 1, 0.3, "claimed"),
  S(5, "morning", L9, "Zed Ashcombe", "Yuri Lindgren", 0, 0.15, "held", "added within the re-cut days"),
  S(5, "late", L7, "Gus Tamarind", "Hal Brightwater", 1, 0.28, "claimed"),
  S(6, "evening", L2, "Zed Ashcombe", "Tad Winslow", 3, 0.64, "claimed"),
  S(6, "evening", L3, "Lou Fairbanks", "Milo Sandoval", 2, 0.4, "claimed"),
  S(6, "evening", L8, "Gus Tamarind", "Hal Brightwater", 1, 0.33, "claimed"),
  S(6, "evening", L5, "Quin Delacroix", "Xan Petrakis", 0, 0.5, "held", "season-costly"),
  S(6, "evening", PRIVATE, "Bram Ellery", "Abe Quill", 0, 0.37, "held", "the private league is never touched"),
];

// ---------------------------------------------------------------- the runs
/** A step as the sample writes it: its name, its minutes, its detail, its data, skipped or not. */
interface StepSpec {
  name: string;
  min: number;
  detail: string;
  data?: Record<string, unknown>;
  skipped?: boolean;
}
const T = (name: string, min: number, detail: string, data?: Record<string, unknown>, skipped?: boolean): StepSpec => ({ name, min, detail, data, skipped });
const count = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const codes = (leagues: string[]) => ({ codes: Object.fromEntries(leagues.map((l) => [l, 200])) });
const plan = (leagues: string[], kind: string) => ({ plan: leagues.map((l) => `${l} ${kind} https://example.invalid/${l} (12 s)`) });

const slotOf = (s: Spec) => s.slot;
const specsOf = (day: number, slot: Slot) => SPECS.filter((s) => s.day === day && slotOf(s) === slot);
const order = (a: Spec, b: Spec) => ALL.indexOf(a.league) - ALL.indexOf(b.league);
const dueOf = (day: number, slot: Slot) => specsOf(day, slot).filter((s) => s.res !== "held").sort(order);
const startLeagues = (day: number) => PUBLIC.filter((_, i) => (i + day) % 3 === 0).slice(0, 3);

const entryId = (s: Spec) => `${DATES[s.day]}:${s.league}:${id(s.add)}:${s.drop ? id(s.drop) : "open"}`;

function passSteps(day: number, slot: Slot, extra: StepSpec[] = []): StepSpec[] {
  const due = dueOf(day, slot);
  const leagues = [...new Set(due.map((s) => s.league))];
  const tally: Record<string, number> = {};
  for (const s of due) tally[s.res] = (tally[s.res] ?? 0) + 1;
  const outcomes = Object.entries(tally).map(([k, v]) => `${v} ${k}`).join(", ");
  return [
    T("api", 0.1, "200 on first check, not restarted"),
    ...extra,
    due.length ? T("fresh_reads", 0.4, `${leagues.length} of ${leagues.length} team pages read`, plan(leagues, "team")) : T("fresh_reads", 0, "nothing to read", undefined, true),
    T("due", 0.1, due.length ? `${count(due.length, "entry", "entries")} due in ${count(leagues.length, "league")}` : "0 entries due: nothing due now", {
      entries: due.map(entryId),
      leagues,
    }),
    due.length
      ? T("moves", Math.max(1, due.length * 0.5), `${count(due.length, "page")} opened in ${count(leagues.length, "league")}: ${outcomes}`, { outcomes: tally, ...plan(leagues, "add") })
      : T("moves", 0, "nothing to open", undefined, true),
    T("start_active", 0, "nothing to open", undefined, true),
  ];
}

const built = (day: number, slots: Slot[]) => {
  const list = slots.flatMap((s) => specsOf(day, s));
  return `${count(list.filter((s) => s.res !== "held").length, "entry", "entries")} queued, ${list.filter((s) => s.res === "held").length} held; leagues private 1, queued 9`;
};
const queueData = { leagues: { queued: PUBLIC, private: [PRIVATE] } };

/** Each day's routines, at their timers, with their steps. */
function daySpecs(day: number): { routine: string; at: string; steps: StepSpec[] }[] {
  const il = dueOf(day, "evening").filter((s) => s.il);
  const runs: { routine: string; at: string; steps: StepSpec[] }[] = [
    { routine: "signin", at: "04:50", steps: [T("browser", 0.5, "the session is signed in")] },
    {
      routine: "daily",
      at: "05:00",
      steps: [
        T("api", 0.2, "200 on first check, not restarted"),
        T("exports", 3, "5 of 5 due saved"),
        T("private_pages", 4, "39 pages opened", plan([PRIVATE], "team")),
        T("refresh", 14, "9 leagues refreshed", codes(PUBLIC)),
        T("solve", 8, "10 leagues solved, all 200", codes(ALL)),
        T("start_active", 2, "3 pages opened in 3 leagues", plan(startLeagues(day), "start")),
        T("lineup", 7, "18 pages opened in 9 leagues", plan(PUBLIC, "lineup")),
        T("queue_build", 2, built(day, ["morning", "late"]), queueData),
        T("digest", 0.5, "10 leagues, posted on the tracker"),
      ],
    },
  ];
  if (day === 0) {
    runs.push({
      routine: "monday",
      at: "06:00",
      steps: [
        T("record", 3, "last week written"),
        T("scorecard", 4, "last week and the season, projected against actual"),
        T("monday", 3, "the verdicts due; at most one change applied"),
        T("queue_build", 2, "the week's first queue, under the new setting", queueData),
      ],
    });
  }
  runs.push(
    { routine: "watchdog", at: "06:45", steps: [T("status", 0.5, "every routine reported")] },
    { routine: "morning", at: "09:15", steps: [...passSteps(day, "morning"), T("check", 0.2, "the passes read back")] },
    {
      routine: "late",
      at: "15:00",
      steps: [
        ...passSteps(day, "late", [T("lineup", 0, "the pre-tip pass sets today's lineups", undefined, true)]),
        T("resolve", 0, "no page opened: nothing to re-solve", undefined, true),
      ],
    },
    {
      routine: "pretip",
      at: day === 5 ? "17:00" : "18:00",
      steps: [
        T("pretip_due", 0.1, day === 5 ? "first slate, started 17:00 for the 18:00 tip" : "first slate, started 18:00 for the 19:00 tip"),
        T("exports", 1, "2 of 2 due saved"),
        T("private_pages", 3, "39 pages opened", plan([PRIVATE], "team")),
        T("solve", 1, "1 league solved", codes([PRIVATE])),
        T("push", 0.2, "1 suggestion pushed to the user"),
        T("lineup", 3, "9 pages opened in 9 leagues", plan(PUBLIC, "lineup")),
        T("resolve", 2, "9 leagues solved, all 200", codes(PUBLIC)),
      ],
    },
    {
      routine: "evening-build",
      at: "21:00",
      steps: [
        T("api", 0.2, "200 on first check, not restarted"),
        T("exports", 3, "5 of 5 due saved"),
        T("refresh", 9, "9 leagues refreshed", codes(PUBLIC)),
        T("solve", 7, "9 leagues solved, all 200", codes(PUBLIC)),
        T("queue_build", 2, built(day, ["evening"]), queueData),
      ],
    },
    {
      routine: "evening-pass",
      at: "22:40",
      steps: [
        ...passSteps(day, "evening", [
          il.length
            ? T("placed_il", 1.5, "1 IL move made for an open-spot claim", plan([...new Set(il.map((s) => s.league))], "il"))
            : T("placed_il", 0, "no placed claim needs an IL move", undefined, true),
        ]),
        T("claim_page", 0.6, "the pending claims read back", plan(PUBLIC.slice(0, 3), "claims")),
      ],
    },
  );
  return runs;
}

interface Built {
  log: RoutineRunLog;
  /** The moves step's window, for the entries it executes. */
  moves: { start: number; end: number } | null;
  /** The queue build's finish, when the run builds the queue. */
  builtAt: string | null;
}

function buildRun(day: number, r: { routine: string; at: string; steps: StepSpec[] }): Built {
  let t = hm(r.at);
  const start = at(day, t);
  let moves: Built["moves"] = null;
  let builtAt: string | null = null;
  const steps: RoutineStepLog[] = r.steps.map((s) => {
    const a = at(day, t);
    t += s.skipped ? 0 : s.min;
    const b = at(day, t);
    if (s.name === "moves" && !s.skipped) moves = { start: Date.parse(a), end: Date.parse(b) };
    if (s.name === "queue_build") builtAt = b;
    return { name: s.name, status: s.skipped ? "skipped" : "ok", detail: s.detail, started: a, finished: b, ...(s.data ? { data: s.data } : {}) };
  });
  const log: RoutineRunLog = {
    routine: r.routine,
    started_at: start,
    finished_at: at(day, t + 0.05),
    refused: null,
    stopped: false,
    steps,
    alerts: [],
    exports: {},
    failed: false,
  };
  return { log, moves, builtAt };
}

// ---------------------------------------------------------------- the payloads
const NOISE_FLOOR = { plan: 0.15, scored: null, moves: 12, needs: 20, applies: "plan" as const };

function entryOf(s: Spec, builtAt: string, pass: Built | undefined, unit: { i: number; n: number }): QueueEntry {
  const queued = s.res !== "held";
  const window = pass?.moves ?? null;
  const outcomeAt = queued && window ? new Date(window.start + ((window.end - window.start) * (unit.i + 1)) / unit.n).toISOString() : null;
  return {
    id: entryId(s),
    date: DATES[s.day],
    league: s.league,
    scoring: "categories",
    set: "three",
    decision: null,
    add: id(s.add),
    drop: s.drop ? id(s.drop) : null,
    from: DATES[Math.min(6, s.day + 1)],
    availability: "W",
    judged: "three",
    gain: s.gain,
    value: s.gain,
    season: s.res === "held" && s.why === "season-costly" ? -0.2 : 0.1,
    season_costly: s.why === "season-costly",
    flag: null,
    floor: { ...NOISE_FLOOR, below: s.why === "below the noise floor" ? "plan" : null },
    bid: { amount: s.bid, reason: "sample", base: s.bid, factor: 1, sizing: 1, typical: 2, typical_from: "sample" },
    queued,
    reason: queued ? null : ((s.why ?? "below the noise floor") as QueueReason),
    rank: null,
    queued_at: queued ? builtAt : null,
    executes_at: pass ? pass.log.started_at : null,
    struck: false,
    bid_struck: false,
    outcome: queued ? (s.res as "claimed" | "failed" | "skipped") : null,
    outcome_reason: queued ? (s.why ?? null) : null,
    outcome_at: outcomeAt,
    resolved: null,
  };
}

function leagueRow(league: string, builtAt: string): QueueLeague {
  if (league === PRIVATE) {
    return { league, scoring: "categories", mode: "off", status: "private", reason: "the private league is never touched" };
  }
  return { league, scoring: "categories", mode: "live", status: "queued", reason: null, cap: 2, cap_from: "the knob", budget: 80, floor: NOISE_FLOOR, built_at: builtAt };
}

function passOf(day: number, kind: string, b: Built, entries: QueueEntry[]): RoutinePass {
  const leagues = [...new Set(entries.map((e) => e.league))];
  const results: Record<string, number> = {};
  for (const e of entries) if (e.outcome) results[e.outcome] = (results[e.outcome] ?? 0) + 1;
  return {
    id: `${DATES[day]}-${kind}`,
    kind: "moves",
    trigger: kind === "evening-pass" ? "routine_evening" : kind === "late" ? "routine_late" : "routine",
    started: b.log.started_at,
    updated: b.log.finished_at ?? b.log.started_at,
    ended: b.log.finished_at,
    end: "done",
    leagues: { done: leagues.length, total: leagues.length, order: leagues },
    entries: { done: entries.length, total: entries.length },
    current: null,
    results,
    summary: null,
  };
}

export interface SampleWeek {
  runs: RoutineRunsPayload;
  queues: QueuePayload[];
  seasons: SeasonSummary[];
  /** "Live" in the Demo: Friday's morning pass, halfway through a claim. */
  liveAt: number;
  /** Where the Demo starts: just before Thursday's morning pass. */
  demoAt: number;
}

function season(league: string): SeasonSummary {
  return {
    league,
    name: null,
    scoring: "categories",
    num_teams: 12,
    public: league !== PRIVATE,
    week: 5,
    end_week: 20,
    my_team: null,
    opponent: null,
    has_snapshot: true,
    updated_at: null,
    sources: [league === PRIVATE ? "extension" : "public"],
    refresh: null,
  };
}

/** A day's pre-tip slates as the route serves them (#472): the first slate an hour before its
 * tip-off, done by the day's pass; on Friday a late slate too, done with nothing to push. */
function pretipOf(day: number, log: RoutineRunLog | undefined): RoutinePretipDay {
  const tip = day === 5 ? "18:00" : "19:00";
  const end = (name: string) => log?.steps.find((s) => s.name === name)?.finished ?? null;
  const slate = (name: "first" | "late", tipAt: string): RoutinePretipDay["slates"][number] => ({
    slate: name,
    tip: at(day, hm(tipAt)),
    start_at: at(day, hm(tipAt) - 60),
    until: at(day, hm(tipAt) - 15),
    done: false,
    missed: false,
    attempts: [],
  });
  const first = slate("first", tip);
  if (log) {
    const started = log.steps.find((s) => s.name === "pretip_due")?.started ?? log.started_at;
    first.done = true;
    first.attempts = [{ started_at: started, outcome: "done", reason: null, solved_at: end("solve"), pushed_at: end("push"), unchanged: false, lineups_at: end("resolve") }];
  }
  const slates = [first];
  if (day === 4) {
    const late = slate("late", "21:30");
    late.done = true;
    late.attempts = [{ started_at: at(day, hm("20:30") + 0.2), outcome: "done", reason: null, solved_at: at(day, hm("20:36")), pushed_at: null, unchanged: true, lineups_at: at(day, hm("20:42")) }];
    slates.push(late);
  }
  return { enabled: true, lead_min: 60, slates };
}

/** The sample week, built fresh on each call (the model never mutates it, a caller may). */
export function sampleWeek(): SampleWeek {
  const byDay: RoutineRunsPayload["by_day"] = [];
  const queues: QueuePayload[] = [];
  let liveAt = 0;
  let demoAt = 0;
  for (let day = 0; day < 7; day++) {
    const built = daySpecs(day).map((r) => buildRun(day, r));
    const run = (routine: string) => built.find((b) => b.log.routine === routine);
    const daily = run("daily");
    const evening = run("evening-build");
    const passes: Record<Slot, Built | undefined> = { morning: run("morning"), late: run("late"), evening: run("evening-pass") };
    const entries: QueueEntry[] = [];
    for (const slot of ["morning", "late", "evening"] as Slot[]) {
      const builtAt = (slot === "evening" ? evening : daily)?.builtAt ?? at(day, 0);
      const due = dueOf(day, slot);
      for (const s of specsOf(day, slot).sort(order)) {
        entries.push(entryOf(s, builtAt, passes[slot], { i: due.indexOf(s), n: due.length }));
      }
    }
    // The day's last pass that executed anything, as the queue reports it once closed.
    const ran = (["evening", "late", "morning"] as Slot[]).map((slot) => ({ slot, b: passes[slot] })).find((x) => x.b?.moves);
    const lastPass = ran?.b
      ? passOf(day, ran.b.log.routine, ran.b, entries.filter((e) => e.queued && e.executes_at === ran.b?.log.started_at))
      : null;
    const builtTimes = [daily?.builtAt, evening?.builtAt].filter((x): x is string => !!x);
    queues.push({
      date: DATES[day],
      built: builtTimes,
      execute_time: "09:15",
      leagues: ALL.map((l) => leagueRow(l, builtTimes[builtTimes.length - 1])),
      entries,
      settings: {
        execute_time: "09:15",
        at: null,
        by: null,
        set: false,
        sunday_execute_time: "22:30",
        sunday_at: null,
        sunday_by: null,
        in_force: day === 6 ? "22:30" : "09:15",
        rules: Object.fromEntries(
          PUBLIC.map((l) => [
            l,
            {
              noise_floor: NOISE_FLOOR,
              daily_cap: { value: 2, from: "the knob" },
              reserve_adds: 1,
              reserve_release: "fri",
              reserve_price: null,
              reserve_price_from: "typical",
              recut_days: 3,
            },
          ]),
        ),
      },
      stop: false,
      now: at(day, 23 * 60 + 59),
      names: NAMES,
      passes: null,
      active: null,
      last_pass: lastPass,
    });
    byDay.push({ date: DATES[day], runs: Object.fromEntries(built.map((b) => [b.log.routine, b.log])), unread: [], pretip: pretipOf(day, run("pretip")?.log) });
    if (day === 4) {
      // Halfway through its claim: each claim's unit is the half minute before its outcome.
      const live = entries.find((e) => e.league === L6 && e.queued);
      if (live?.outcome_at) liveAt = Date.parse(live.outcome_at) - 15_000;
    }
    if (day === 3) demoAt = Date.parse(passes.morning?.log.started_at ?? at(day, hm("09:15"))) - 60_000;
  }
  return {
    runs: { date: DATES[6], days: 7, by_day: byDay },
    queues,
    seasons: ALL.map(season),
    liveAt,
    demoAt,
  };
}

const SLOTS = ["PG", "SG", "G", "SF", "PF", "F", "C", "C", "Util", "Util", "BN", "BN", "BN", "IL", "IL", "IL"];

/** One sample league's roster as the week begins (invented): the players its moves drop that
 * week first, then others from the sample's names, an open spot where the week adds to one. */
export function sampleRoster(league: string): { slot: string; name: string | null }[] {
  const specs = SPECS.filter((s) => s.league === league && s.res !== "held");
  const adds = new Set(specs.map((s) => s.add));
  const names: string[] = [];
  for (const s of specs) if (s.drop && !adds.has(s.drop) && !names.includes(s.drop)) names.push(s.drop);
  const start = ALL.indexOf(league) * 3;
  for (let k = 0; names.length < 13 && k < PLAYERS.length * 2; k++) {
    const n = PLAYERS[(start + k) % PLAYERS.length];
    if (!adds.has(n) && !names.includes(n)) names.push(n);
  }
  const open = specs.filter((s) => !s.drop).length;
  return SLOTS.map((slot, k) => ({ slot, name: k < 13 ? (k >= 13 - open ? null : (names[k] ?? null)) : null }));
}
