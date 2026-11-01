// The step rail (#282, the side-rail header): one row per step down the left of the card, the
// current one lit, the past ones filled, a row past the written steps still to come. A daily
// track gives each row its time of day; the draft's loop is a bracket from the room back to
// survival. No React, so the test runs under Node.
import type { Track } from "./types";

export type RailState = "cur" | "done" | "todo" | "soon";

export interface RailItem {
  i: number;
  label: string;
  /** The row's time of day, "hh:mm", on a track with hours; null for a row without one. */
  time: string | null;
  state: RailState;
  /** Whether a click opens the step: false for a step still to come. */
  can: boolean;
}

/** An hour of the day as "hh:mm", to the nearest minute. */
export function railTime(h: number): string {
  const m = Math.round(h * 60);
  return `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

/** Whether the track's rows carry a time column (its hours match its labels one to one). */
export function railTimed(track: Track): boolean {
  return !!track.hours && track.hours.length === track.labels.length;
}

/** The rows of the rail with `step` (0-based) current. */
export function railItems(track: Track, step: number): RailItem[] {
  const hours = railTimed(track) ? track.hours : undefined;
  const written = track.steps.length;
  return track.labels.map((label, i) => {
    const can = i < written;
    const state: RailState = i === step ? "cur" : i < step ? "done" : can ? "todo" : "soon";
    const h = hours?.[i];
    return { i, label, time: h === undefined || h === null ? null : railTime(h), state, can };
  });
}

/** The track's loop when it runs from a later row back to an earlier one on the rail. */
export function railLoop(track: Track): Track["loop"] {
  const l = track.loop;
  const n = track.labels.length;
  return l && l.from < n && l.to >= 0 && l.to < l.from ? l : undefined;
}

/** Where this browser keeps the rail folded to its dots or open (#282). */
export const RAIL_KEY = "pickandroll.explain.rail";

/** The rail is open unless this browser kept it folded; a value it does not know reads as open. */
export function railOpen(saved: string | null): boolean {
  return saved !== "folded";
}
