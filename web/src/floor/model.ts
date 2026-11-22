// The floor's model (FLOOR PR 3, #460): the routines' run reports, their live progress, the
// day's queues, the leagues and the status sheet in; a timeline out: the runs and their steps,
// the agent each step goes to, the units riding between stations, the queue's entries and the
// passes, each with its start and end on the clock (epoch milliseconds). No React and no fetch,
// so the test runs under Node.

import type {
  QueueEntry,
  QueuePayload,
  QueueRules,
  RoutineLivePayload,
  RoutinePretipDay,
  RoutinePass,
  RoutineProgress,
  RoutineRunLog,
  RoutineRunsPayload,
  RoutineStepLog,
  SeasonSummary,
  StatusPayload,
} from "../api.ts";

// ---------------------------------------------------------------- the cast
export type Agent = "scout" | "solver" | "setter" | "starter" | "mover" | "orchestrator";

/** The floor's stations: the Sources room's three, the Solver's engine, the orchestrator's desk,
 * the queue's belt, the execute-time gate and the leagues' docks. */
export type Station = "bbm" | "espn" | "yahoo" | "engine" | "desk" | "belt" | "gate" | "docks";

export interface Cast {
  agent: Agent;
  /** Where the step's units start and where they ride to. */
  from: Station;
  to: Station;
}

export const AGENTS: Record<Agent, { label: string; does: string }> = {
  scout: { label: "Scout", does: "reads pages and exports" },
  solver: { label: "Solver", does: "solves moves and lineups" },
  setter: { label: "Setter", does: "sets lineups" },
  starter: { label: "Starter", does: "presses Start Active" },
  mover: { label: "Mover", does: "places claims, adds and drops" },
  orchestrator: { label: "Orchestrator", does: "builds the queue, applies the rules, opens the gate" },
};

const C = (agent: Agent, from: Station, to: Station): Cast => ({ agent, from, to });

/** Each routine step's agent (the master's ruling on #457): one table. Reads for the solve ride
 * from the Sources room into the engine, reads made at a pass ride to the execute-time gate. */
export const CAST: Readonly<Record<string, Cast>> = {
  // the Scout
  bbm: C("scout", "bbm", "desk"),
  yahoo: C("scout", "yahoo", "desk"),
  browser: C("scout", "yahoo", "desk"),
  exports: C("scout", "bbm", "engine"),
  private_pages: C("scout", "yahoo", "engine"),
  lineup_pages: C("scout", "yahoo", "engine"),
  refresh: C("scout", "yahoo", "engine"),
  fresh_reads: C("scout", "yahoo", "gate"),
  claim_page: C("scout", "yahoo", "gate"),
  // the Solver
  solve: C("solver", "engine", "desk"),
  resolve: C("solver", "engine", "desk"),
  resolve_comebacks: C("solver", "engine", "desk"),
  monday: C("solver", "engine", "desk"),
  // the Setter, the Starter, the Mover
  lineup: C("setter", "desk", "docks"),
  start_active: C("starter", "desk", "docks"),
  moves: C("mover", "gate", "docks"),
  placed_il: C("mover", "gate", "docks"),
  cancel: C("mover", "gate", "docks"),
  comebacks: C("mover", "desk", "docks"),
  // the orchestrator's own, named
  queue_build: C("orchestrator", "desk", "belt"),
  due: C("orchestrator", "belt", "gate"),
};

/** A step's agent: the table's, else the orchestrator at its desk. */
export function castOf(step: string | null): Cast {
  return (step !== null && CAST[step]) || C("orchestrator", "desk", "desk");
}

/** A routine's systemd timer on the routine host (Central): once a day at ``at``, or every
 * ``every`` minutes from ``from`` to ``to`` (the pre-tip check, ``09..20:00/5``). */
export type Timer = { label: string; at: string } | { label: string; every: number; from: string; to: string };

/** The routines: their timers (``ops/vm/*.timer``) and their names on the floor. A routine not
 * here (one added later) plays as a generic run. */
export const ROUTINES: Readonly<Record<string, Timer>> = {
  signin: { label: "sign-in check", at: "04:50" },
  daily: { label: "daily", at: "05:00" },
  monday: { label: "Monday", at: "06:00" },
  watchdog: { label: "watchdog", at: "06:45" },
  morning: { label: "morning pass", at: "09:15" },
  late: { label: "late pass", at: "15:00" },
  pretip: { label: "pre-tip", every: 5, from: "09:00", to: "20:55" },
  "evening-build": { label: "evening build", at: "21:00" },
  "evening-pass": { label: "evening pass", at: "22:40" },
};

export const routineLabel = (routine: string): string => ROUTINES[routine]?.label ?? routine;

/** The orchestrator's own steps at its desk, named in the run reports but not in ``CAST`` (they
 * fall to the orchestrator there): the API check, the read-backs, the posts, the pre-tip's own. */
export const DESK_STEPS = [
  "api", "check", "status", "digest", "post", "record", "scorecard", "sunday", "pretip_due", "push", "day_file", "lineups_logged",
] as const;

/** Each routine's steps as its run report names them (``scripts/routine.py``), for the gates
 * strip's lanes before a run reports (#472); held to ``CAST`` and ``DESK_STEPS`` by a test. The
 * watchdog writes no run report: no steps. */
export const ROUTINE_AGENTS: Readonly<Record<string, readonly string[]>> = {
  signin: ["browser", "bbm", "yahoo"],
  daily: ["api", "exports", "private_pages", "lineup_pages", "refresh", "solve", "start_active", "lineup", "check", "resolve_comebacks", "queue_build", "digest", "post"],
  monday: ["api", "record", "private_pages", "scorecard", "monday", "solve", "queue_build"],
  watchdog: [],
  morning: ["api", "due", "moves", "start_active", "check", "fresh_reads", "comebacks"],
  late: ["api", "lineup", "due", "moves", "start_active", "resolve", "comebacks", "fresh_reads", "check", "status"],
  pretip: ["api", "pretip_due", "exports", "private_pages", "lineup_pages", "solve", "push", "day_file", "lineup", "resolve", "check", "status", "lineups_logged"],
  "evening-build": ["api", "exports", "refresh", "solve", "queue_build"],
  "evening-pass": ["api", "placed_il", "cancel", "due", "moves", "start_active", "claim_page", "check", "sunday", "fresh_reads"],
};

// ---------------------------------------------------------------- the rules
/** The queue's seven rules on the belt, in the order the queue build applies them
 * (``season/autopilot.py``, ``queue_of``), each with the reasons it holds an entry for. */
export const BELT = [
  { key: "waiver_days", tag: "waiver days", reasons: ["the add is a player this queue drops today or dropped within the waiver days"] },
  { key: "noise_floor", tag: "noise floor", reasons: ["below the noise floor"] },
  { key: "reserve", tag: "reserve", reasons: ["held for the week's reserve"] },
  { key: "recut", tag: "re-cut", reasons: ["added within the re-cut days"] },
  {
    key: "week_plan",
    tag: "week plan",
    reasons: ["a later step of the week plan: queued at its day's build", "an earlier step of the week plan is not queued"],
  },
  {
    key: "no_adds",
    tag: "no adds left",
    reasons: ["no adds left this week", "this week's adds are not fully read: the transactions reads do not reach its start"],
  },
  { key: "day_cap", tag: "day cap", reasons: ["over the day's cap"] },
] as const;

export type BeltRule = (typeof BELT)[number]["key"];

/** The Solver's two signs (the user's ruling): part of every search, not gates. The queue reads
 * each again, and an entry it holds there is held at the sign. */
export const SIGNS = [
  { key: "keep", tag: "keep rule", reasons: ["the drop is protected"] },
  { key: "guard", tag: "season guard", reasons: ["season-costly"] },
] as const;

export type Sign = (typeof SIGNS)[number]["key"];

/** Where an entry is held: at a rule of the belt, at a sign of the Solver, at the orchestrator's
 * desk (a claim already placed on its add or drop, a reason the floor does not know), or at its
 * league's dock (the private league, a league whose executor is off). */
export type Hold =
  | { at: "belt"; rule: BeltRule; reason: string }
  | { at: "sign"; sign: Sign; reason: string }
  | { at: "desk"; reason: string }
  | { at: "league"; reason: string };

/** A rebuild's leftover (``SUPERSEDED``, #209): it holds no place and is never due, so it is left
 * off the floor; the timeline only counts it. */
export const SUPERSEDED = "superseded by a later solve";
export const isSuperseded = (e: Pick<QueueEntry, "reason" | "superseded_at">): boolean => !!e.superseded_at || e.reason === SUPERSEDED;

const LEAGUE_REASONS = [
  "the private league is never touched",
  "the moves executor is off in this league",
];

/** The hold of an entry the queue did not queue; null for a queued one and for a superseded one.
 * The orchestrator's desk takes, on purpose, the two reasons of a claim already placed (on the add,
 * on the drop: the queue's own check, not a rule of the belt) and any reason the floor does not
 * know. A drop on Yahoo's can't-cut list is no reason of its own: the keep rule protects it, and
 * its entry stands at the keep sign as "the drop is protected". */
export function holdOf(e: Pick<QueueEntry, "queued" | "reason" | "superseded_at">): Hold | null {
  if (e.queued || isSuperseded(e)) return null;
  const reason: string = e.reason ?? "held";
  const rule = BELT.find((r) => (r.reasons as readonly string[]).includes(reason));
  if (rule) return { at: "belt", rule: rule.key, reason };
  const sign = SIGNS.find((r) => (r.reasons as readonly string[]).includes(reason));
  if (sign) return { at: "sign", sign: sign.key, reason };
  if (LEAGUE_REASONS.includes(reason)) return { at: "league", reason };
  return { at: "desk", reason };
}

// ---------------------------------------------------------------- the timeline
export interface FloorUnit {
  league: string | null;
  /** A moves pass's entry, when the unit is one. */
  entry: string | null;
  start: number;
  end: number;
}

export interface FloorStep {
  /** Null for a step under way that has not said its name (it follows ``after``). */
  name: string | null;
  after: string | null;
  cast: Cast;
  status: "ok" | "failed" | "skipped" | "running";
  detail: string;
  start: number;
  /** Null while it runs. */
  end: number | null;
  units: FloorUnit[];
}

export type RunState = "done" | "failed" | "refused" | "stopped" | "running" | "stale";

export interface FloorRun {
  key: string;
  routine: string;
  label: string;
  date: string;
  state: RunState;
  start: number;
  /** Null while it runs; a stale run ends at its file's last write. */
  end: number | null;
  steps: FloorStep[];
}

export type Outcome = NonNullable<QueueEntry["outcome"]>;

export interface FloorEntry {
  id: string;
  date: string;
  league: string;
  add: number;
  drop: number | null;
  addName: string;
  dropName: string | null;
  gain: number | null;
  bid: number | null;
  queued: boolean;
  hold: Hold | null;
  struck: boolean;
  /** When the build put it on the queue (its league's last build of the day). */
  builtAt: number;
  executesAt: number | null;
  outcome: Outcome | null;
  outcomeReason: string | null;
  outcomeAt: number | null;
}

export interface FloorPass {
  id: string;
  kind: RoutinePass["kind"];
  trigger: RoutinePass["trigger"];
  start: number;
  end: number | null;
  leagues: RoutinePass["leagues"];
  entries: RoutinePass["entries"];
  current: { league: string; entry: string | null; since: number } | null;
}

export interface FloorLeague {
  league: string;
  public: boolean;
  scoring: SeasonSummary["scoring"];
  /** The moves executor's mode on the newest queue. */
  mode: string | null;
}

/** Whether the run reports (``/routine/runs`` and ``/routine/live``) have been read (#480):
 * until both have, a gate with no report is not known, never missed, and nothing reads idle. */
export type Reports = "loaded" | "loading" | "failed";

export interface Timeline {
  runs: FloorRun[];
  entries: FloorEntry[];
  passes: FloorPass[];
  leagues: FloorLeague[];
  /** Each league's gates on the newest queue that carries them (#458). */
  rules: Record<string, QueueRules>;
  /** The entries left off the floor as superseded by a later solve, for the ledger. */
  superseded: number;
  /** Each day's pre-tip slates, from the run reports' ``pretip`` block (#472). */
  pretip: Record<string, RoutinePretipDay>;
  /** When each source was last read, from the status sheet; ESPN is a still station. */
  sources: Record<"bbm" | "yahoo" | "espn", number | null>;
  /** The run reports read, still loading, or failed (#480); the Demo's are always read. */
  reports: Reports;
  start: number;
  end: number;
}

export interface Inputs {
  runs?: RoutineRunsPayload | null;
  live?: RoutineLivePayload | null;
  queues?: (QueuePayload | null | undefined)[];
  seasons?: SeasonSummary[] | null;
  status?: StatusPayload | null;
  /** Live: whether the runs and the live payload have loaded (#480); read when left out. */
  reports?: Reports;
  now: number;
}

const ms = (iso: string | null | undefined): number | null => (iso ? Date.parse(iso) : null);

/** When a decision was solved, from its stamp (``20261120T032141223108-moves-bbm``, UTC); null
 * for a stamp that does not read. */
export function decisionAt(stamp: string | null | undefined): number | null {
  const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(\d{3})?/.exec(stamp ?? "");
  if (!m) return null;
  const t = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6], m[7] ? +m[7] : 0);
  return Number.isNaN(t) ? null : t;
}

/** The league a run's per-league line names first ("223259 lineup https://..."). */
const leadLeague = (line: unknown): string | null => {
  const m = typeof line === "string" ? /^(\d+)\s/.exec(line) : null;
  return m ? m[1] : null;
};

/** ``2026-11-10:224319:6433:5161``: the league of a queue entry's id. */
const entryLeague = (id: string): string | null => id.split(":")[1] ?? null;

/** Units spread evenly over ``[start, end]``. */
function spread(items: { league: string | null; entry: string | null }[], start: number, end: number): FloorUnit[] {
  const n = items.length;
  return items.map((u, i) => ({ ...u, start: start + ((end - start) * i) / n, end: start + ((end - start) * (i + 1)) / n }));
}

/** A step's units, from what it logged: the leagues of its codes or its plan, the entries it
 * found due; a moves step's entries are the queue's whose outcome landed inside it, each ending
 * at its outcome. */
function unitsOf(step: RoutineStepLog, start: number, end: number, entries: FloorEntry[]): FloorUnit[] {
  const data = step.data ?? {};
  if (step.name === "moves") {
    const landed = entries
      .filter((e) => e.outcomeAt !== null && e.outcomeAt >= start && e.outcomeAt <= end)
      .sort((a, b) => (a.outcomeAt ?? 0) - (b.outcomeAt ?? 0));
    if (landed.length) {
      let at = start;
      return landed.map((e) => {
        const u = { league: e.league, entry: e.id, start: at, end: e.outcomeAt ?? end };
        at = u.end;
        return u;
      });
    }
  }
  if (Array.isArray(data.entries) && data.entries.every((x) => typeof x === "string")) {
    const ids = data.entries as string[];
    return spread(ids.map((id) => ({ league: entryLeague(id), entry: id })), start, end);
  }
  if (data.codes && typeof data.codes === "object") {
    return spread(Object.keys(data.codes).map((league) => ({ league, entry: null })), start, end);
  }
  if (Array.isArray(data.plan)) {
    const leagues = data.plan.map(leadLeague).filter((l): l is string => l !== null);
    return spread(leagues.map((league) => ({ league, entry: null })), start, end);
  }
  return [];
}

function stepsOf(log: RoutineStepLog[], runStart: number, entries: FloorEntry[]): FloorStep[] {
  let prev = runStart;
  return log.map((s) => {
    const start = ms(s.started) ?? prev;
    const end = ms(s.finished) ?? start;
    prev = end;
    return {
      name: s.name,
      after: null,
      cast: castOf(s.name),
      status: s.status,
      detail: s.detail,
      start,
      end,
      units: s.status === "skipped" ? [] : unitsOf(s, start, end, entries),
    };
  });
}

function runOf(date: string, log: RoutineRunLog, entries: FloorEntry[]): FloorRun {
  const start = ms(log.started_at) ?? 0;
  const steps = stepsOf(log.steps, start, entries);
  const end = ms(log.finished_at) ?? (steps.length ? (steps[steps.length - 1].end ?? start) : start);
  const state: RunState = log.refused ? "refused" : log.stopped ? "stopped" : log.failed ? "failed" : "done";
  return { key: `${date}-${log.routine}`, routine: log.routine, label: routineLabel(log.routine), date, state, start, end, steps };
}

/** A run in flight, from its live progress file: its finished steps and the step under way. */
function liveRunOf(p: RoutineProgress, stale: boolean, written: number | null, entries: FloorEntry[]): FloorRun {
  const start = ms(p.started_at) ?? 0;
  const steps = stepsOf(p.steps, start, entries);
  if (!stale) {
    steps.push({
      name: p.current.name,
      after: p.current.after,
      cast: castOf(p.current.name),
      status: "running",
      detail: p.current.name ? `${p.current.name} under way` : `under way after ${p.current.after ?? "the start"}`,
      start: ms(p.current.started) ?? start,
      end: null,
      units: [],
    });
  }
  const date = centralDate(start);
  return {
    key: `${date}-${p.routine}`,
    routine: p.routine,
    label: routineLabel(p.routine),
    date,
    state: stale ? "stale" : "running",
    start,
    end: stale ? written : null,
    steps,
  };
}

function entryOf(e: QueueEntry, q: QueuePayload): FloorEntry {
  const row = q.leagues.find((l) => l.league === e.league);
  // A queued entry carries when it was queued; a held one does not, so it stands from its own
  // solve (the decision stamp), else from the day's first build (a rebuild keeps holding it); a
  // queued one without the time stands from its row's build.
  const firstBuild = ms(q.built[0]);
  const solved = decisionAt(e.decision);
  const builtAt = ms(e.queued_at) ?? (e.queued ? ms(row?.built_at) : (solved ?? firstBuild)) ?? ms(row?.built_at) ?? firstBuild ?? ms(q.now) ?? 0;
  const name = (id: number | null) => (id === null ? null : (q.names?.[String(id)] ?? `#${id}`));
  return {
    id: e.id,
    date: e.date,
    league: e.league,
    add: e.add,
    drop: e.drop,
    addName: name(e.add) ?? `#${e.add}`,
    dropName: name(e.drop),
    gain: e.gain,
    bid: e.bid?.amount ?? null,
    queued: e.queued,
    hold: holdOf(e),
    struck: e.struck,
    builtAt,
    executesAt: ms(e.executes_at),
    outcome: e.outcome,
    outcomeReason: e.outcome_reason,
    outcomeAt: ms(e.outcome_at),
  };
}

function passOf(p: RoutinePass): FloorPass {
  return {
    id: p.id,
    kind: p.kind,
    trigger: p.trigger,
    start: ms(p.started) ?? 0,
    end: ms(p.ended),
    leagues: p.leagues,
    entries: p.entries,
    current: p.current ? { league: p.current.league, entry: p.current.entry, since: ms(p.current.since) ?? 0 } : null,
  };
}

/** The timeline of every payload given: runs from the logs and the live files (a live file
 * whose run already logged is left out), entries and passes from each day's queue. */
export function timeline(i: Inputs): Timeline {
  const queues = (i.queues ?? []).filter((q): q is QueuePayload => !!q).sort((a, b) => a.date.localeCompare(b.date));
  const all = queues.flatMap((q) => q.entries.map((e) => ({ e, q })));
  const entries = all.filter(({ e }) => !isSuperseded(e)).map(({ e, q }) => entryOf(e, q));
  const runs: FloorRun[] = [];
  for (const day of i.runs?.by_day ?? []) {
    for (const log of Object.values(day.runs)) runs.push(runOf(day.date, log, entries));
  }
  for (const row of i.live?.live ?? []) {
    if (!row.progress) continue;
    const start = ms(row.progress.started_at);
    if (runs.some((r) => r.routine === row.progress?.routine && r.start === start)) continue;
    runs.push(liveRunOf(row.progress, row.stale, ms(row.written_at), entries));
  }
  runs.sort((a, b) => a.start - b.start);
  const passes = new Map<string, FloorPass>();
  for (const q of queues) {
    for (const p of [q.last_pass, q.active]) if (p) passes.set(p.id, passOf(p));
  }
  const newest = queues[queues.length - 1];
  const mode = new Map((newest?.leagues ?? []).map((l) => [l.league, l.mode as string]));
  const leagues: FloorLeague[] = (i.seasons ?? []).map((s) => ({
    league: s.league,
    public: s.public,
    scoring: s.scoring,
    mode: mode.get(s.league) ?? null,
  }));
  const rules = [...queues].reverse().find((q) => q.settings.rules && Object.keys(q.settings.rules).length)?.settings.rules ?? {};
  const exportsAt = (i.status?.exports.rows ?? []).map((r) => ms(r.as_of)).filter((t): t is number => t !== null);
  const yahooAt = (i.status?.leagues ?? [])
    .flatMap((l) => l.yahoo?.rows ?? [])
    .map((r) => ms(r.read_at))
    .filter((t): t is number => t !== null);
  const times = [
    ...runs.flatMap((r) => [r.start, r.end ?? i.now]),
    ...entries.flatMap((e) => [e.builtAt, e.outcomeAt ?? e.builtAt]),
  ];
  return {
    runs,
    entries,
    passes: [...passes.values()].sort((a, b) => a.start - b.start),
    leagues,
    rules,
    superseded: all.length - entries.length,
    pretip: Object.fromEntries((i.runs?.by_day ?? []).filter((d) => d.pretip).map((d) => [d.date, d.pretip as RoutinePretipDay])),
    sources: {
      bbm: exportsAt.length ? Math.max(...exportsAt) : null,
      yahoo: yahooAt.length ? Math.max(...yahooAt) : null,
      espn: null,
    },
    reports: i.reports ?? "loaded",
    start: times.length ? Math.min(...times) : i.now,
    end: Math.max(i.now, ...times),
  };
}

// ---------------------------------------------------------------- the floor at a moment
export type EntryState = "unbuilt" | "held" | "struck" | "queued" | "doing" | Outcome;
export type StepState = "todo" | "doing" | "done" | "skipped";

/** An entry's state at ``t``: not built yet, held at its rule, struck, queued, under way in a
 * pass (the live pass's current entry, or the unit under way), or its outcome once it landed. */
export function entryState(e: FloorEntry, t: number, pass?: FloorPass | null, unit?: FloorUnit | null): EntryState {
  if (t < e.builtAt) return "unbuilt";
  if (!e.queued) return "held";
  if (e.outcome !== null && e.outcomeAt !== null && t >= e.outcomeAt) return e.outcome;
  if (pass && pass.current?.entry === e.id && t >= pass.current.since && (pass.end === null || t < pass.end)) return "doing";
  // A finished pass read back (the Demo, a past day) names no current entry: its unit does.
  if (unit && unit.entry === e.id && t >= unit.start && t < unit.end) return "doing";
  if (e.struck) return "struck";
  return "queued";
}

export function stepState(s: FloorStep, t: number): StepState {
  if (t < s.start) return "todo";
  if (s.status === "skipped") return "skipped";
  if (s.end === null || t < s.end) return "doing";
  return "done";
}

export interface FloorNow {
  /** The run under way at ``t``, its step and that step's unit. */
  run: FloorRun | null;
  step: FloorStep | null;
  unit: FloorUnit | null;
  /** The pass under way at ``t``. */
  pass: FloorPass | null;
  /** With no run under way: the timer that fires next. */
  next: { routine: string; label: string; at: number } | null;
}

const within = (t: number, a: number, b: number | null) => t >= a && (b === null || t < b);

/** The floor at ``t``. A day at rest has no run, the next timer and every entry where it rests;
 * a run in flight names its step (the one under way, or the last one past its end). */
export function floorAt(tl: Timeline, t: number): FloorNow {
  const run = tl.runs.find((r) => within(t, r.start, r.state === "running" ? null : r.end)) ?? null;
  const pass = tl.passes.find((p) => within(t, p.start, p.end)) ?? null;
  if (!run) return { run: null, step: null, unit: null, pass, next: nextTimer(t) };
  let step = run.steps.find((s) => within(t, s.start, s.end)) ?? run.steps[run.steps.length - 1] ?? null;
  // A step the run has not named (its live file says only what it follows) is the pass's own when
  // a pass is under way: the moves step's Mover, the lineup step's Setter.
  if (step && step.status === "running" && step.name === null && pass && pass.end === null) {
    const name = pass.kind === "moves" ? "moves" : "lineup";
    const done = pass.entries?.total ? ` · entry ${Math.min(pass.entries.done + 1, pass.entries.total)} of ${pass.entries.total}` : "";
    step = { ...step, name, cast: castOf(name), detail: `${name} under way${done}` };
  }
  const unit = step?.units.find((u) => t >= u.start && t < u.end) ?? null;
  return { run, step, unit, pass, next: null };
}

// ---------------------------------------------------------------- the Central clock
const hm = (s: string): number => Number(s.slice(0, 2)) * 60 + Number(s.slice(3, 5));

const CENTRAL = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/Chicago",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

function centralParts(t: number): { date: string; minutes: number } {
  const p = Object.fromEntries(CENTRAL.formatToParts(new Date(t)).map((x) => [x.type, x.value]));
  return { date: `${p.year}-${p.month}-${p.day}`, minutes: Number(p.hour) * 60 + Number(p.minute) };
}

/** The Central day of ``t``, ``YYYY-MM-DD``. */
export const centralDate = (t: number): string => centralParts(t).date;

/** ``minutes`` past Central midnight on ``date`` (to 24:00, the next midnight), as epoch ms. */
export function centralAt(date: string, minutes: number): number {
  const base = Date.parse(`${date}T00:00:00Z`);
  if (minutes >= 1440) return centralAt(new Date(base + 86_400_000).toISOString().slice(0, 10), minutes - 1440);
  for (const off of [6, 5]) {
    const t = base + (minutes + off * 60) * 60_000;
    const p = centralParts(t);
    if (p.date === date && p.minutes === Math.floor(minutes)) return t;
  }
  return base + (minutes + 6 * 60) * 60_000;
}

/** ``HH:MM`` as minutes past midnight. */
export const minutesOf = hm;

/** Each timer's minutes past Central midnight in a day, the once-a-day timers first, so a check
 * that falls on a once-a-day timer's minute (the pre-tip at 09:15 or 15:00) gives way to it. */
const TICKS = Object.entries(ROUTINES)
  .flatMap(([routine, r]) => {
    if ("at" in r) return [{ routine, label: r.label, min: hm(r.at), fixed: true }];
    const ticks = [];
    for (let m = hm(r.from); m <= hm(r.to); m += r.every) ticks.push({ routine, label: r.label, min: m, fixed: false });
    return ticks;
  })
  .sort((a, b) => a.min - b.min || Number(b.fixed) - Number(a.fixed));

/** The next routine timer after ``t`` on the Central clock: Monday's only on a Monday, the pre-tip
 * check's next five-minute tick inside its window. */
export function nextTimer(t: number): { routine: string; label: string; at: number } {
  for (let day = 0; day < 8; day++) {
    const base = t + day * 86_400_000;
    const { minutes } = centralParts(base);
    const dayStart = base - minutes * 60_000 - (base % 60_000);
    const weekday = new Date(dayStart + 12 * 3_600_000).getUTCDay();
    for (const x of TICKS) {
      if (x.routine === "monday" && weekday !== 1) continue;
      const at = dayStart + x.min * 60_000;
      if (at > t) return { routine: x.routine, label: x.label, at };
    }
  }
  return { routine: "daily", label: ROUTINES.daily.label, at: t + 86_400_000 };
}


// ---------------------------------------------------------------- the Demo's bent clock
export interface BentClock {
  /** Wall seconds from the Demo's start to its end. */
  wallEnd: number;
  toTime(wall: number): number;
  toWall(t: number): number;
}

/** The Demo's clock over a timeline (the mock-up's): every run slowed to a few seconds of wall
 * time, a step by its length and its units, and the idle hours between runs skipped (0.7 s
 * between runs of a day, 1.4 s into a new day). Piecewise linear, so wall and time map both ways. */
export function bentClock(tl: Timeline): BentClock {
  const knots: [number, number][] = [];
  let wall = 0.6;
  let prevDate: string | null = null;
  const done = tl.runs.filter((r) => r.end !== null);
  if (!done.length) {
    return { wallEnd: 1, toTime: () => tl.start, toWall: () => 0 };
  }
  knots.push([0, done[0].start - 20 * 60_000]);
  for (const r of done) {
    wall += prevDate === null ? 0 : r.date !== prevDate ? 1.4 : 0.7;
    prevDate = r.date;
    knots.push([wall, r.start]);
    for (const s of r.steps) {
      const end = s.end ?? s.start;
      const minutes = (end - s.start) / 60_000;
      const span = s.status === "skipped" ? 0.22 : Math.max(0.4, Math.min(3, 0.4 + 0.5 * Math.sqrt(minutes)), s.units.length * 0.2);
      wall += span;
      knots.push([wall, end]);
    }
    if (knots[knots.length - 1][1] < (r.end ?? r.start)) {
      wall += 0.2;
      knots.push([wall, r.end ?? r.start]);
    }
  }
  wall += 1.2;
  knots.push([wall, knots[knots.length - 1][1] + 20 * 60_000]);
  const at = (xs: [number, number][], v: number, from: 0 | 1): number => {
    const to = from === 0 ? 1 : 0;
    if (v <= xs[0][from]) return xs[0][to];
    for (let k = 1; k < xs.length; k++) {
      const [a, b] = [xs[k - 1], xs[k]];
      if (v <= b[from]) {
        const span = b[from] - a[from];
        return span <= 0 ? b[to] : a[to] + ((b[to] - a[to]) * (v - a[from])) / span;
      }
    }
    return xs[xs.length - 1][to];
  };
  // A time inside no run keeps its place between the runs it falls between; equal times map to
  // the first wall second they reach.
  return { wallEnd: wall, toTime: (w) => at(knots, w, 0), toWall: (t) => at(knots, t, 1) };
}
