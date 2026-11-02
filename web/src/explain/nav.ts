// Where the reader is (#283): the track and the step, kept in the URL hash as `#draft/3` (the
// number the step shows: a track's overview 0, its steps from one), and the moves between steps.
// No React, so the test runs under Node.
import type { Track, TrackId } from "./types";

export interface Place {
  track: TrackId;
  /** The step's index, from zero. */
  step: number;
}

export const TRACK_ORDER: TrackId[] = ["draft", "moves", "daily"];

export const HOME: Place = { track: "draft", step: 0 };

const isTrack = (v: string): v is TrackId => (TRACK_ORDER as string[]).includes(v);

/** Whether the track opens on an unnumbered overview (#282): its first step marked `intro`. */
export function hasIntro(t: Track | undefined): boolean {
  return t?.steps[0]?.intro === true;
}

/** The number step `i` (0-based) shows, and its hash carries: the overview 0, the steps from 1. */
export function stepNumber(t: Track | undefined, i: number): number {
  return hasIntro(t) ? i : i + 1;
}

/** How many numbered steps the track plans: its rail labels, less the overview. */
export function plannedSteps(t: Track): number {
  return t.labels.length - (hasIntro(t) ? 1 : 0);
}

/** The bar's count on step `i`: "Overview" on the overview, "3 of 9" on a step. */
export function stepCount(t: Track, i: number): string {
  return hasIntro(t) && i === 0 ? "Overview" : `${stepNumber(t, i)} of ${plannedSteps(t)}`;
}

/** The place a hash names, or the first step of the first track; a track named alone opens on
 * its first step (the overview where it has one); a step past the end lands on the last, a
 * number before the first on the first. */
export function parseHash(hash: string, tracks: Track[]): Place {
  const m = /^#?([a-z]+)(?:\/(\d+))?$/.exec(hash.trim());
  if (!m || !isTrack(m[1])) return HOME;
  const t = tracks.find((x) => x.id === m[1]);
  const n = t?.steps.length ?? 0;
  const at = m[2] === undefined ? 0 : Number(m[2]) - stepNumber(t, 0);
  return { track: m[1], step: Math.min(Math.max(0, at), Math.max(0, n - 1)) };
}

export function formatHash(p: Place, tracks: Track[]): string {
  return `#${p.track}/${stepNumber(tracks.find((t) => t.id === p.track), p.step)}`;
}

/** The step `delta` away: past a track's last step the next track's first, its overview where
 * it has one (the last track stays on its last step); before a track's first step, the previous
 * track's last. The overview is a step like the others, so the arrows walk into it. */
export function move(p: Place, delta: number, tracks: Track[]): Place {
  const n = (id: TrackId) => tracks.find((t) => t.id === id)?.steps.length ?? 0;
  const k = TRACK_ORDER.indexOf(p.track);
  const to = p.step + delta;
  if (to >= n(p.track)) {
    if (k >= TRACK_ORDER.length - 1) return { track: p.track, step: Math.max(0, n(p.track) - 1) };
    return { track: TRACK_ORDER[k + 1], step: 0 };
  }
  if (to < 0) {
    if (k === 0) return { track: p.track, step: 0 };
    const prev = TRACK_ORDER[k - 1];
    return { track: prev, step: Math.max(0, n(prev) - 1) };
  }
  return { track: p.track, step: to };
}

/** The → arrow's words on a step (its title): the last step of a track leads to the next track. */
export function nextLabel(p: Place, tracks: Track[]): string {
  const n = tracks.find((t) => t.id === p.track)?.steps.length ?? 0;
  if (p.step < n - 1) return "Next →";
  const k = TRACK_ORDER.indexOf(p.track);
  if (k >= TRACK_ORDER.length - 1) return "Done";
  const next = tracks.find((t) => t.id === TRACK_ORDER[k + 1]);
  return `Next: ${next?.title ?? "the next track"} →`;
}
