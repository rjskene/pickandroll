// The explainer's data shapes (#283): a track is a list of steps, a step is a title, its bullets
// and a figure. Types only, so the track modules and the text-rule test run under Node.

/** One key idea, with its sub-ideas; two levels, never more (the user's rule, #282). A term in
 * the text is written `[id]` or `[id|the words shown]` and renders as a `dfn` that opens the
 * glossary on `id`. */
export interface Bullet {
  text: string;
  sub?: string[];
}

/** The figure beside a step's bullets, by name; the screen maps each name to its component. */
export type FigureId = "export-row" | "weekly-odds" | "day-line";

export interface Step {
  /** The hash's name for the step (`#draft/projections`). */
  id: string;
  title: string;
  /** The words after the step count in the kicker ("step 1 of 9 · projections"). */
  kicker: string;
  bullets: Bullet[];
  figure: FigureId;
  /** The figure takes the card's full width (the day line). */
  wide?: boolean;
  /** Where the rules shown come from: files in the repo, in the reader's words. */
  source: string[];
}

export type TrackId = "draft" | "moves" | "daily";

export interface Track {
  id: TrackId;
  /** The track control's label. */
  title: string;
  /** The line over the strip, with the track's name in bold. */
  lede: string;
  /** The strip's short label per step, in step order: the whole planned track, so a dot past
   * the written steps shows as still to come. */
  labels: string[];
  steps: Step[];
}

/** A glossary entry: one line each. */
export interface Term {
  id: string;
  term: string;
  def: string;
}
