// Where the reader is (#283): the track and the step, kept in the URL hash as `#draft/3` (the
// step counted from one), and the moves between steps. No React, so the test runs under Node.
import type { Track, TrackId } from "./types";

export interface Place {
  track: TrackId;
  /** The step's index, from zero. */
  step: number;
}

export const TRACK_ORDER: TrackId[] = ["draft", "moves", "daily"];

export const HOME: Place = { track: "draft", step: 0 };

const isTrack = (v: string): v is TrackId => (TRACK_ORDER as string[]).includes(v);

/** The place a hash names, or the first step of the first track; a step past the end lands on
 * the last, a step before one on the first. */
export function parseHash(hash: string, tracks: Track[]): Place {
  const m = /^#?([a-z]+)(?:\/(\d+))?$/.exec(hash.trim());
  if (!m || !isTrack(m[1])) return HOME;
  const n = tracks.find((t) => t.id === m[1])?.steps.length ?? 0;
  const step = m[2] === undefined ? 0 : Math.min(Math.max(0, Number(m[2]) - 1), Math.max(0, n - 1));
  return { track: m[1], step };
}

export function formatHash(p: Place): string {
  return `#${p.track}/${p.step + 1}`;
}

/** The step `delta` away: past a track's last step the next track's first (the last track
 * stays on its last step); before a track's first step, the previous track's last. */
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

/** The Next button's words on a step: the last step of a track leads to the next track. */
export function nextLabel(p: Place, tracks: Track[]): string {
  const n = tracks.find((t) => t.id === p.track)?.steps.length ?? 0;
  if (p.step < n - 1) return "Next →";
  const k = TRACK_ORDER.indexOf(p.track);
  if (k >= TRACK_ORDER.length - 1) return "Done";
  const next = tracks.find((t) => t.id === TRACK_ORDER[k + 1]);
  return `Next: ${next?.title ?? "the next track"} →`;
}
