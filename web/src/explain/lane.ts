// The lane model (#283): one lane per action, segments in time, each open, running,
// blocked, done, idle or over; the words for each; the events a clock steps between. No React,
// so the test runs under Node.

export type SegKind = "open" | "run" | "block" | "done" | "after" | "idle";

export interface Seg {
  /** From `a` to `b` on the chart's axis. */
  a: number;
  b: number;
  k: SegKind;
  /** The readout's sentence while the marker is in this segment. */
  l: string;
  /** The badge's word, when not the kind's own. */
  w?: string;
}

export interface Mark {
  at: number;
  /** An instant (an amber diamond) or a hard stop (a dashed red line). */
  k: "tick" | "stop";
}

export interface Lane {
  name: string;
  /** The dim line under the name, on a desktop. */
  sub?: string;
  segs: Seg[];
  marks?: Mark[];
}

export const WORD: Record<SegKind, string> = { open: "open", run: "running", block: "blocked", done: "done", after: "ran", idle: "—" };

/** The segment the marker is in at `t` (the last one past the end). */
export function laneState(ln: Lane, t: number): Seg {
  return ln.segs.find((g) => t >= g.a && t < g.b) ?? ln.segs[ln.segs.length - 1];
}

export function laneWord(g: Seg): string {
  return g.w ?? WORD[g.k];
}

/** Every time something changes on any lane, ascending. */
export function laneEvents(lanes: Lane[]): number[] {
  const s = new Set<number>();
  for (const ln of lanes) {
    for (const g of ln.segs) {
      s.add(g.a);
      s.add(g.b);
    }
    for (const m of ln.marks ?? []) s.add(m.at);
  }
  return [...s].sort((a, b) => a - b);
}

/** The event before `t`, or `min`. */
export function prevEvent(events: number[], t: number, min: number): number {
  const e = [...events].reverse().find((x) => x < t - 1e-6);
  return e === undefined ? min : e;
}

/** The event after `t`, or `max`. */
export function nextEvent(events: number[], t: number, max: number): number {
  const e = events.find((x) => x > t + 1e-6);
  return e === undefined ? max : e;
}

/** Minutes of the day as a clock reading; 1440 reads 24:00. */
export function hhmm(t: number): string {
  if (t >= 1440) return "24:00";
  return `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(Math.floor(t) % 60).padStart(2, "0")}`;
}

/** Hours and minutes as minutes of the day. */
export const M = (h: number, m = 0): number => h * 60 + m;
