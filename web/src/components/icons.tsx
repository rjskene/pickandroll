import type { ReactElement } from "react";
import type { CardId } from "../draft";
import type { ProgressCardId, ProgressViewId, SeasonCardId, SeasonViewId } from "../keys";

const stroke = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

export const CARD_ICONS: Record<CardId, ReactElement> = {
  pick: (
    <svg width="20" height="20" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="4" />
      <path d="M12 3v3M12 18v3M3 12h3M18 12h3" />
    </svg>
  ),
  cats: (
    <svg width="20" height="20" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <path d="M4 20h16M6 16V9M10 16V5M14 16v-7M18 16v-4" />
    </svg>
  ),
  alts: (
    <svg width="20" height="20" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
    </svg>
  ),
  plan: (
    <svg width="20" height="20" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <circle cx="6" cy="19" r="2.5" />
      <circle cx="18" cy="5" r="2.5" />
      <path d="M8.5 19H14a3 3 0 0 0 0-6h-4a3 3 0 0 1 0-6h5.5" />
    </svg>
  ),
  team: (
    <svg width="20" height="20" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <circle cx="9" cy="8" r="3.5" />
      <path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M21.5 20a6.5 6.5 0 0 0-5-6.3" />
    </svg>
  ),
  log: (
    <svg width="20" height="20" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </svg>
  ),
  solver: (
    <svg width="20" height="20" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0" />
      <circle cx="16" cy="6" r="2" />
      <circle cx="10" cy="12" r="2" />
      <circle cx="18" cy="18" r="2" />
    </svg>
  ),
  sync: (
    <svg width="20" height="20" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <path d="M20 11a8 8 0 0 0-14.3-4.9L4 8" />
      <path d="M4 3v5h5" />
      <path d="M4 13a8 8 0 0 0 14.3 4.9L20 16" />
      <path d="M20 21v-5h-5" />
    </svg>
  ),
};

export const SEASON_ICONS: Record<SeasonCardId, ReactElement> = {
  waivers: (
    <svg width="20" height="20" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
    </svg>
  ),
  moves: (
    <svg width="20" height="20" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <path d="M7 4v16M3 8l4-4 4 4M17 20V4M13 16l4 4 4-4" />
    </svg>
  ),
  trade: (
    <svg width="20" height="20" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <path d="M4 8h14l-3-3M20 16H6l3 3" />
    </svg>
  ),
  flags: (
    <svg width="20" height="20" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <path d="M5 21V4M5 4h11l-2 4 2 4H5" />
    </svg>
  ),
  roster: (
    <svg width="20" height="20" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <circle cx="9" cy="8" r="3.5" />
      <path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M21.5 20a6.5 6.5 0 0 0-5-6.3" />
    </svg>
  ),
  league: (
    <svg width="20" height="20" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0V4zM17 6h3v2a3 3 0 0 1-3 3M7 6H4v2a3 3 0 0 0 3 3" />
    </svg>
  ),
  // A frontier: this week against the rest of the season.
  strategy: (
    <svg width="20" height="20" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <path d="M3 3v18h18M6 6c3 0 7 1 9 4s3 7 3 8" />
      <circle cx="9.5" cy="6.8" r="1.5" />
      <circle cx="16" cy="12" r="1.5" />
    </svg>
  ),
  // A card scored: a week's projection against its result.
  scorecard: (
    <svg width="20" height="20" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <rect x="4" y="3" width="16" height="18" rx="2" />
      <path d="M8 8h8M8 12h5M8 16l2 2 4-4" />
    </svg>
  ),
  // A queue against a clock: the day's moves and when they execute.
  queue: (
    <svg width="20" height="20" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <path d="M3 6h9M3 12h7M3 18h9" />
      <circle cx="17.5" cy="12" r="4.5" />
      <path d="M17.5 9.5V12l1.5 1.5" />
    </svg>
  ),
};

/** The view drawer's tabs (#116). */
export const VIEW_ICONS: Record<SeasonViewId, ReactElement> = {
  waivers: (
    <svg width="18" height="18" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <path d="M4 6h16M4 12h16M4 18h10" />
    </svg>
  ),
  // Two sides and the line between them.
  matchup: (
    <svg width="18" height="18" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <path d="M3 12h7M14 12h7M10 6v12M14 6v12" />
    </svg>
  ),
  // A calendar: the weeks ahead.
  season: (
    <svg width="18" height="18" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <rect x="4" y="5" width="16" height="15" rx="2" />
      <path d="M4 10h16M9 3v4M15 3v4" />
    </svg>
  ),
  // A grid: slots down, days across.
  lineup: (
    <svg width="18" height="18" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <path d="M4 9h16M4 14h16M10 4v16" />
    </svg>
  ),
};

/** The Progress screen's cards and views (#129). */
export const PROGRESS_ICONS: Record<ProgressCardId, ReactElement> = {
  // A page with its sections: the Monday note.
  note: (
    <svg width="20" height="20" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <path d="M6 3h9l4 4v14H6zM15 3v4h4M9 11h7M9 15h7M9 19h4" />
    </svg>
  ),
  // Two sliders: the knobs.
  knobs: (
    <svg width="20" height="20" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <path d="M4 7h16M4 17h16" />
      <circle cx="9" cy="7" r="2.2" />
      <circle cx="15" cy="17" r="2.2" />
    </svg>
  ),
  league: SEASON_ICONS.league,
  // A target: the odds against where they landed.
  odds: (
    <svg width="20" height="20" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <circle cx="12" cy="12" r="8" />
      <circle cx="12" cy="12" r="3.5" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
    </svg>
  ),
};

/** Card 3 in the Moves view (#129): the move chosen. */
export const PROGRESS_MOVE_ICON = SEASON_ICONS.moves;

export const PROGRESS_VIEW_ICONS: Record<ProgressViewId, ReactElement> = {
  // A climbing line over a baseline.
  trend: (
    <svg width="18" height="18" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <path d="M3 20h18M4 16l5-5 4 3 7-8" />
      <path d="M4 14h16" strokeDasharray="2 3" />
    </svg>
  ),
  moves: (
    <svg width="18" height="18" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <path d="M7 4v16M3 8l4-4 4 4M17 20V4M13 16l4 4 4-4" />
    </svg>
  ),
  odds: (
    <svg width="18" height="18" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <circle cx="12" cy="12" r="8" />
      <circle cx="12" cy="12" r="3.5" />
    </svg>
  ),
  // A grid: leagues down, weeks across.
  table: (
    <svg width="18" height="18" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M3 9h18M3 14h18M9 4v16" />
    </svg>
  ),
};

export function Chevron({ dir }: { dir: "up" | "down" | "left" | "right" }) {
  const d = { up: "m6 15 6-6 6 6", down: "m6 9 6 6 6-6", left: "m15 6-6 6 6 6", right: "m9 6 6 6-6 6" }[dir];
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

export function Grip() {
  return (
    <svg width="18" height="8" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <circle cx="6" cy="9" r="1.6" />
      <circle cx="12" cy="9" r="1.6" />
      <circle cx="18" cy="9" r="1.6" />
      <circle cx="6" cy="15" r="1.6" />
      <circle cx="12" cy="15" r="1.6" />
      <circle cx="18" cy="15" r="1.6" />
    </svg>
  );
}

export function GripV() {
  return (
    <svg width="8" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <circle cx="9" cy="6" r="1.6" />
      <circle cx="15" cy="6" r="1.6" />
      <circle cx="9" cy="12" r="1.6" />
      <circle cx="15" cy="12" r="1.6" />
      <circle cx="9" cy="18" r="1.6" />
      <circle cx="15" cy="18" r="1.6" />
    </svg>
  );
}

export function Close() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <path d="M6 6l12 12M18 6 6 18" />
    </svg>
  );
}

export function Swap() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <path d="M8 4v16M8 4 5 7M8 4l3 3M16 20V4M16 20l-3-3M16 20l3-3" />
    </svg>
  );
}

/** The freshness light's three states as shapes (#253), so the state reads without its colour: a
 * check in a circle (up to date), a clock face (pending), an exclamation mark in a triangle
 * (failed). The colour is the caller's tone class. */
export function StatusGlyph({ state, size = 18 }: { state: "green" | "amber" | "red"; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      {state === "green" && (
        <>
          <circle cx="12" cy="12" r="9" />
          <path d="m8 12.5 2.7 2.7L16 9.5" />
        </>
      )}
      {state === "amber" && (
        <>
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v5l3.2 2" />
        </>
      )}
      {state === "red" && (
        <>
          <path d="M10.3 4.2 2.6 17.6A2 2 0 0 0 4.3 20.6h15.4a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0Z" />
          <path d="M12 9.5v4.5M12 17.2h.01" />
        </>
      )}
    </svg>
  );
}

/** The Progress screen (#253): a rising line over a baseline. */
export function ProgressIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <path d="M3 20h18" />
      <path d="m4 16 5-5 4 3 7-8" />
      <path d="M16 6h4v4" />
    </svg>
  );
}

/** All leagues, the landing page (#253): four tiles in a 2×2 grid. */
export function LeaguesIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <rect x="4" y="4" width="6.5" height="6.5" rx="1.5" />
      <rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5" />
      <rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5" />
      <rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5" />
    </svg>
  );
}
