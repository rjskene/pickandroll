// The day's gates under the floor (#472): when each agent acts on a Central day, from 04:30 to
// midnight, one lane an agent. A routine's timer is a gate on the lanes of the agents its steps
// use; a run that reported draws its steps as bars from their start to their finish; a run in
// flight pulses; a timer still to come is a hollow mark; one 20 minutes past with no report and
// nothing running is missed. The pre-tip check is drawn by its slates, the queue's execute times
// sit on the Mover's lane. No React and no fetch, so the test runs under Node.

import type { RoutinePretipAttempt, RoutinePretipSlate } from "../api.ts";
import { AGENTS, ROUTINES, ROUTINE_AGENTS, castOf, centralAt, centralDate, minutesOf } from "./model.ts";
import type { Agent, FloorRun, Reports, Timeline } from "./model.ts";

/** The lanes, top to bottom: the cast's order (the issue's ruling). */
export const LANES: readonly Agent[] = ["scout", "solver", "orchestrator", "setter", "starter", "mover"];

/** The strip's day: 04:30 to 24:00 Central. */
export const FROM_MIN = 4 * 60 + 30;
export const TO_MIN = 24 * 60;
/** A gate this long past its time with no report and nothing running is missed. */
export const GRACE_MS = 20 * 60_000;

/** A gate's state: reported done (all its steps ok), done with a failed step, done with nothing
 * to do, in flight, still to come, missed; ``plain`` for the watchdog, which reports nothing. */
export type GateState = "done" | "failed" | "idle" | "running" | "todo" | "missed" | "plain";
export type BarState = "ok" | "failed" | "idle" | "running";

export interface GateLine {
  agent: Agent;
  name: string;
  status: BarState;
  detail: string;
}

export interface GateBar {
  agent: Agent;
  start: number;
  end: number;
  state: BarState;
}

export interface Gate {
  key: string;
  kind: "routine" | "slate" | "execute" | "watchdog";
  routine: string;
  label: string;
  /** The scheduled time: the timer's, a slate's start, an execute time. */
  at: number;
  state: GateState;
  /** The run's actual start and finish, when it ran (finish null while it runs). */
  start: number | null;
  end: number | null;
  lanes: Agent[];
  bars: GateBar[];
  lines: GateLine[];
  /** An execute time's count of queued entries. */
  count: number | null;
  /** A short note for the hover: the slate's tip-off, a missed gate's "not run". */
  note: string | null;
}

/** A faint band on lanes: the pre-tip check's window on a future day, its slates not yet known. */
export interface GateBand {
  key: string;
  start: number;
  end: number;
  lanes: Agent[];
  label: string;
}

export interface DayGates {
  date: string;
  from: number;
  to: number;
  /** Where the now line stands, null when ``t`` is not on this day's strip. */
  now: number | null;
  /** Before, on or after the day of ``t``. */
  when: "past" | "today" | "future";
  gates: Gate[];
  bands: GateBand[];
  /** Why no gate reads missed while the run reports are not read (#480), else null. */
  note: string | null;
}

const ms = (iso: string | null | undefined): number | null => (iso ? Date.parse(iso) : null);
const weekday = (date: string) => new Date(Date.parse(`${date}T12:00:00Z`)).getUTCDay();

/** A step that ran with nothing to do: skipped, or ok with nothing needed or nothing due. */
const IDLE = /^(nothing\b|0 entries due\b)/;
function barState(status: "ok" | "failed" | "skipped" | "running", detail: string): BarState {
  if (status === "running") return "running";
  if (status === "failed") return "failed";
  if (status === "skipped" || IDLE.test(detail)) return "idle";
  return "ok";
}

const lanesOf = (steps: readonly (string | null)[]): Agent[] => {
  const seen = new Set(steps.map((s) => castOf(s).agent));
  return LANES.filter((a) => seen.has(a));
};

/** A run's steps by ``t`` as bars and lines; the step under way ends at ``t``. */
function barsOf(run: FloorRun, t: number): { bars: GateBar[]; lines: GateLine[] } {
  const bars: GateBar[] = [];
  const lines: GateLine[] = [];
  for (const s of run.steps) {
    if (s.start > t) continue;
    const agent = s.cast.agent;
    const running = s.status === "running" || s.end === null || t < s.end;
    const state = running ? "running" : barState(s.status, s.detail);
    bars.push({ agent, start: s.start, end: Math.min(s.end ?? t, t), state });
    lines.push({ agent, name: s.name ?? `after ${s.after ?? "the start"}`, status: state, detail: s.detail });
  }
  return { bars, lines };
}

/** A reported run's state at ``t``: in flight until its end, else by its steps and its flags. */
function runState(run: FloorRun, t: number, bars: GateBar[]): GateState {
  if (run.state === "running" || run.end === null || t < run.end) return "running";
  if (run.state === "failed" || run.state === "refused" || run.state === "stale" || bars.some((b) => b.state === "failed")) return "failed";
  if (run.state === "stopped" || (bars.length > 0 && bars.every((b) => b.state === "idle"))) return "idle";
  return "done";
}

/** What the strip says while the run reports are not read (#480). */
export const REPORTS_NOTE: Record<Exclude<Reports, "loaded">, string> = {
  loading: "run reports loading",
  failed: "run reports not loaded",
};

/** A gate not reported by ``t``: still to come, due inside the grace, else missed. Its time
 * past while the run reports are not read, it is not known: a plain tick, never missed (#480). */
const unreported = (at: number, t: number, reports: Reports): GateState =>
  t < at ? "todo" : reports !== "loaded" ? "plain" : t - at > GRACE_MS ? "missed" : "todo";
const unreportedNote = (state: GateState, reports: Reports): string | null =>
  state === "missed" ? "not run" : state === "plain" && reports !== "loaded" ? REPORTS_NOTE[reports] : null;

const hhmm = (t: number) => {
  const d = new Date(t);
  return new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(d);
};

/** A pre-tip attempt's end: its lineups, its push, its solve, else a minute on. */
const attemptEnd = (a: RoutinePretipAttempt, start: number) => ms(a.lineups_at) ?? ms(a.pushed_at) ?? ms(a.solved_at) ?? start + 60_000;

/** One pre-tip slate's gate. Its attempts are the day file's; the one the day's run report holds
 * (the day's last pass: the report is rewritten) draws its steps, an earlier one spans the
 * pre-tip's lanes from its start to its last stamp. */
function slateGate(date: string, slate: RoutinePretipSlate, runs: FloorRun[], t: number, enabled: boolean, latest: string | undefined, reports: Reports): Gate | null {
  const attempts = slate.attempts.filter((a) => (ms(a.started_at) ?? Infinity) <= t);
  const at = ms(slate.start_at) ?? ms(attempts[0]?.started_at) ?? null;
  if (at === null) return null;
  if (!enabled && !attempts.length) return null;
  const lanes = lanesOf(ROUTINE_AGENTS.pretip);
  const tip = ms(slate.tip);
  const until = ms(slate.until) ?? (tip !== null ? tip - 15 * 60_000 : at + 45 * 60_000);
  const bars: GateBar[] = [];
  const lines: GateLine[] = [];
  let start: number | null = null;
  let end: number | null = null;
  let running = false;
  for (const a of attempts) {
    const s = ms(a.started_at) as number;
    const run = runs.find((r) => r.start <= s + 5_000 && s <= (r.end ?? t));
    const from = run ? null : "from the day file";
    start = start ?? s;
    if (run) {
      const b = barsOf(run, t);
      bars.push(...b.bars);
      lines.push(...b.lines);
      running ||= runState(run, t, b.bars) === "running";
      end = run.end === null || t < run.end ? null : run.end;
    } else {
      const e = Math.min(attemptEnd(a, s), t);
      const state: BarState = a.outcome === "failed" ? "failed" : a.outcome === "done" ? "ok" : "idle";
      for (const agent of lanes) bars.push({ agent, start: s, end: e, state });
      end = e;
    }
    const stamps = [a.solved_at && `solved ${hhmm(Date.parse(a.solved_at))}`, a.pushed_at && `pushed ${hhmm(Date.parse(a.pushed_at))}`, a.unchanged && "nothing to push", a.lineups_at && `lineups ${hhmm(Date.parse(a.lineups_at))}`];
    lines.push({
      agent: "orchestrator",
      name: `attempt ${hhmm(s)}`,
      status: a.outcome === "failed" ? "failed" : a.outcome === "done" ? "ok" : "idle",
      detail: [a.outcome, ...stamps.filter(Boolean), a.reason, from].filter(Boolean).join(" · "),
    });
  }
  // A pass in flight in the slate's window that has not logged an attempt yet.
  const live = runs.find((r) => (r.state === "running" || (r.end !== null && t < r.end)) && r.start >= at - 5 * 60_000 && r.start <= until && r.start <= t);
  if (live && !attempts.some((a) => Math.abs((ms(a.started_at) ?? 0) - live.start) < 60_000 || (ms(a.started_at) ?? 0) >= live.start)) {
    const b = barsOf(live, t);
    bars.push(...b.bars);
    lines.push(...b.lines);
    running = true;
    start = start ?? live.start;
    end = null;
  }
  const last = attempts[attempts.length - 1];
  // A slate starting past the latest start is never made due: grey, never missed.
  const byDesign = !!slate.past_latest && !attempts.length && !running;
  const state: GateState = byDesign
    ? "idle"
    : running
    ? "running"
    : attempts.some((a) => a.outcome === "done")
      ? "done"
      : last?.outcome === "failed"
        ? "failed"
        : last?.outcome === "missed" || (slate.missed && t >= until)
          ? "missed"
          : last
            ? t >= until ? "missed" : "idle"
            : unreported(at, t, reports);
  const name = slate.slate === "first" ? "first slate" : "late slate";
  return {
    key: `${date}-pretip-${slate.slate}`,
    kind: "slate",
    routine: "pretip",
    label: `pre-tip, ${name}`,
    at,
    state,
    start,
    end: running ? null : end,
    lanes,
    bars,
    lines,
    count: null,
    note:
      [
        tip !== null ? `tip-off ${hhmm(tip)}` : null,
        byDesign ? `starts past ${latest ?? "the latest start"}: not run by design` : null,
        unreportedNote(state, reports),
      ]
        .filter(Boolean)
        .join(" · ") || null,
  };
}

/** The gates of Central ``date`` as they stand at ``t``: a past day shows what ran and what was
 * missed, a future day what is still to come. */
export function gatesOf(tl: Timeline, date: string, t: number): DayGates {
  const from = centralAt(date, FROM_MIN);
  const to = centralAt(date, TO_MIN);
  const today = centralDate(t);
  const when = date < today ? "past" : date > today ? "future" : "today";
  const gates: Gate[] = [];
  const dayRuns = tl.runs.filter((r) => r.date === date && r.start <= t);
  for (const [routine, timer] of Object.entries(ROUTINES)) {
    if (!("at" in timer)) continue;
    if (routine === "monday" && weekday(date) !== 1) continue;
    const at = centralAt(date, minutesOf(timer.at));
    const base = { routine, label: timer.label, at, count: null };
    if (routine === "watchdog") {
      gates.push({ ...base, key: `${date}-${routine}`, kind: "watchdog", state: "plain", start: null, end: null, lanes: [], bars: [], lines: [], note: "writes no run report" });
      continue;
    }
    const run = dayRuns.filter((r) => r.routine === routine).sort((a, b) => b.start - a.start)[0];
    if (run) {
      const { bars, lines } = barsOf(run, t);
      const state = runState(run, t, bars);
      gates.push({ ...base, key: run.key, kind: "routine", state, start: run.start, end: state === "running" ? null : run.end, lanes: lanesOf(run.steps.map((s) => s.name)), bars, lines, note: null });
      continue;
    }
    const state = unreported(at, t, tl.reports);
    if (state === "todo" && when === "past") continue;
    gates.push({
      ...base,
      key: `${date}-${routine}`,
      kind: "routine",
      state,
      start: null,
      end: null,
      lanes: lanesOf(ROUTINE_AGENTS[routine] ?? []),
      bars: [],
      lines: [],
      note: unreportedNote(state, tl.reports),
    });
  }
  // The pre-tip check by its slates: the day's pre-tip runs feed them.
  const pretip = tl.pretip[date];
  const pretipRuns = dayRuns.filter((r) => r.routine === "pretip");
  for (const slate of pretip?.slates ?? []) {
    const g = slateGate(date, slate, pretipRuns, t, pretip.enabled, pretip.latest_start, tl.reports);
    if (g && !(when === "future" && g.state !== "todo")) gates.push(g);
  }
  // An API before the block: each pre-tip run is a gate at its start.
  if (!pretip) {
    for (const run of pretipRuns) {
      const { bars, lines } = barsOf(run, t);
      const state = runState(run, t, bars);
      const label = ROUTINES.pretip.label;
      gates.push({ key: run.key, kind: "slate", routine: "pretip", label, at: run.start, state, start: run.start, end: state === "running" ? null : run.end, lanes: lanesOf(run.steps.map((x) => x.name)), bars, lines, count: null, note: null });
    }
  }
  // The queue's execute times on the Mover's lane, each with its count of queued entries.
  const byAt = new Map<number, typeof tl.entries>();
  for (const e of tl.entries) {
    if (!e.queued || e.executesAt === null || e.builtAt > t || centralDate(e.executesAt) !== date) continue;
    byAt.set(e.executesAt, [...(byAt.get(e.executesAt) ?? []), e]);
  }
  for (const [at, es] of [...byAt].sort((a, b) => a[0] - b[0])) {
    const landed = es.filter((e) => e.outcomeAt !== null && e.outcomeAt <= t);
    const passing = tl.passes.some((p) => p.kind === "moves" && p.start <= t && (p.end === null || t < p.end));
    const state: GateState =
      landed.length === es.length ? (landed.some((e) => e.outcome === "failed") ? "failed" : "done") : t < at ? "todo" : passing ? "running" : "todo";
    gates.push({
      key: `${date}-execute-${at}`,
      kind: "execute",
      routine: "execute",
      label: "execute time",
      at,
      state,
      start: null,
      end: null,
      lanes: ["mover"],
      bars: [],
      lines: es.map((e) => ({
        agent: "mover" as const,
        name: `${e.league} ${e.addName}${e.dropName ? ` for ${e.dropName}` : ""}`,
        status: e.outcome === "failed" ? "failed" : e.outcome && e.outcomeAt !== null && e.outcomeAt <= t ? (e.outcome === "claimed" ? "ok" : "idle") : "idle",
        detail: e.outcome && e.outcomeAt !== null && e.outcomeAt <= t ? e.outcome : "queued",
      })),
      count: es.length,
      note: `${es.length} queued ${es.length === 1 ? "entry" : "entries"}`,
    });
  }
  gates.sort((a, b) => a.at - b.at);
  // A future day: the pre-tip check's window as one faint band, its slates set from that day's tip-offs.
  const bands: GateBand[] = [];
  const pt = ROUTINES.pretip;
  if (when === "future" && "every" in pt) {
    bands.push({
      key: `${date}-pretip-window`,
      start: centralAt(date, minutesOf(pt.from)),
      end: centralAt(date, minutesOf(pt.to)),
      lanes: lanesOf(ROUTINE_AGENTS.pretip),
      label: `pre-tip window ${pt.from}-${pt.to}: its slates are set from the day's tip-offs on the day`,
    });
  }
  const note = tl.reports === "loaded" ? null : REPORTS_NOTE[tl.reports];
  return { date, from, to, now: t >= from && t <= to ? t : null, when, gates, bands, note };
}

/** Live, ← or → on the floor (#472): the gates' day ``delta`` days on inside ``week``, stopping at
 * its first day and at today; null when that is today (no day picked). */
export function stepGateDay(week: readonly string[], today: string, current: string, delta: number): string | null {
  const days = week.filter((d) => d <= today);
  if (!days.length) return null;
  // A future day (picked by a click) stands one past today, so ← comes back to today.
  const k = current > today ? days.length : Math.max(0, days.indexOf(current));
  const d = days[Math.max(0, Math.min(days.length - 1, k + delta))];
  return d === today ? null : d;
}

/** The hover's lines: the label, the scheduled time, the actual start and finish, the status,
 * and the lane's steps (all its steps off a lane) with their detail lines. */
export function gateTip(g: Gate, lane: Agent | null): string[] {
  const status: Record<GateState, string> = {
    done: "done",
    failed: "done, a step failed",
    idle: "done, nothing to do",
    running: "running",
    todo: "still to come",
    missed: "not run",
    plain: "no run report",
  };
  const out = [`${g.label} · ${hhmm(g.at)}`];
  if (g.start !== null) out.push(`ran ${hhmm(g.start)}${g.end !== null ? ` to ${hhmm(g.end)}` : ", under way"}`);
  // A routine's plain tick is one not known while the run reports load (#480); the watchdog's is its own.
  const said = g.state === "idle" && g.start === null ? "no run" : g.state === "plain" && g.kind !== "watchdog" ? "not known yet" : status[g.state];
  out.push(said + (g.note && g.state !== "missed" ? ` · ${g.note}` : ""));
  const lines = g.lines.filter((l) => lane === null || l.agent === lane || g.kind === "slate" && l.name.startsWith("attempt"));
  for (const l of lines.slice(0, 12)) out.push(`${AGENTS[l.agent].label} · ${l.name}: ${l.detail || l.status}`);
  if (lines.length > 12) out.push(`… ${lines.length - 12} more`);
  return out;
}

// Where a tooltip centered on the pointer goes (#474): its center stays at least half its own width
// plus the margin from each edge of the box, so a tip of any width stays inside; a tip wider than
// the box (less both margins) is centered in it.
export function tipCenter(boxWidth: number, tipWidth: number, x: number, margin = 8): number {
  const lo = tipWidth / 2 + margin;
  const hi = boxWidth - tipWidth / 2 - margin;
  if (lo > hi) return boxWidth / 2;
  return Math.max(lo, Math.min(hi, x));
}
