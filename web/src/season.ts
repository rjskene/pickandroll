// The season view's pure helpers (#92): labels for ages, ownership and availability, and the
// available table's filters and sort. No React, so `npm test` runs them under Node.
import type { AvailableRow, SeasonPlayer, SeasonRefresh, SeasonSummary, SeasonTeamRef, SeasonWeek } from "./api";

/** "4 min ago": how old a snapshot is. */
export function ageLabel(iso: string | null | undefined, now: number): string {
  if (!iso) return "never read";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const minutes = Math.floor((now - t) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.floor(hours / 24)} days ago`;
}

/** True when the snapshot is older than a day: its rosters and pool have likely moved. */
export function isStale(iso: string | null | undefined, now: number): boolean {
  if (!iso) return true;
  const t = Date.parse(iso);
  return Number.isNaN(t) || now - t > 24 * 3600_000;
}

/** "46%" for a percentage Yahoo shows as a whole number. */
export function pctLabel(x: number | null | undefined): string {
  return x == null ? "" : `${Math.round(x)}%`;
}

/** "+3" or "−1" for the day's change in percent rostered; nothing when it did not move. */
export function changeLabel(x: number | null | undefined): string {
  if (x == null || x === 0) return "";
  return x > 0 ? `+${x}` : `−${Math.abs(x)}`;
}

/** "FA", or "W · Oct 22" for a player on waivers until that date. */
export function availabilityLabel(row: Pick<AvailableRow, "availability" | "clears">): string {
  if (row.availability !== "W") return "FA";
  if (!row.clears) return "W";
  const d = new Date(`${row.clears}T12:00:00`);
  return `W · ${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`;
}

/** Yahoo's codes that keep a player off the floor, as `season/state.py`'s OUT_CODES. */
const OUT = new Set(["O", "INJ", "SUSP", "NA", "OFS"]);

/** The tag colour for a player's status: out in red, doubtful or questionable in amber. */
export function statusTone(player: Pick<SeasonPlayer, "status">): "bad" | "accent" | null {
  const s = player.status;
  if (!s) return null;
  return OUT.has(s) ? "bad" : "accent";
}

/** A status's words and the injury note, for the tag's hover. */
export function statusTitle(player: Pick<SeasonPlayer, "status" | "status_full" | "note">): string | undefined {
  if (!player.status) return undefined;
  return [player.status_full ?? player.status, player.note].filter(Boolean).join(": ");
}

/** "3-1-0 · 2nd": a team's record and rank, as the league page shows them. */
export function recordLabel(team: SeasonTeamRef | null | undefined): string {
  if (!team) return "";
  const rank = team.rank != null ? ` · ${ordinal(team.rank)}` : "";
  return `${team.record ?? "no record"}${rank}`;
}

export function ordinal(n: number): string {
  const tens = n % 100;
  const suffix = tens >= 11 && tens <= 13 ? "th" : (["th", "st", "nd", "rd"][n % 10] ?? "th");
  return `${n}${suffix}`;
}

/** What a league's refresh is doing, in a few words; nothing once it is done. */
export function refreshNote(refresh: SeasonRefresh | null | undefined): string {
  if (!refresh || refresh.status === "done") return "";
  // The step is the last one read; the calendar and the schedule come after the counted pages.
  if (refresh.status === "running") return refresh.total ? `refreshing ${refresh.done}/${refresh.total} · ${refresh.step}` : "refreshing";
  return refresh.error ?? refresh.status;
}

export function isRefreshing(s: Pick<SeasonSummary, "refresh"> | null | undefined): boolean {
  return s?.refresh?.status === "running";
}

/** "Oct 19 – 25", or "Mar 29 – Apr 4" across a month. */
export function weekDates(week: Pick<SeasonWeek, "start" | "end">): string {
  const day = (iso: string) => new Date(`${iso}T12:00:00`);
  const a = day(week.start);
  const b = day(week.end);
  const month = (d: Date) => d.toLocaleDateString("en-US", { month: "short" });
  const end = a.getMonth() === b.getMonth() ? String(b.getDate()) : `${month(b)} ${b.getDate()}`;
  return `${month(a)} ${a.getDate()} – ${end}`;
}

/** "Week 1 of 22". */
export function weekLabel(s: Pick<SeasonSummary, "week" | "end_week">): string {
  if (s.week == null) return "week unknown";
  return s.end_week != null ? `Week ${s.week} of ${s.end_week}` : `Week ${s.week}`;
}

// ---------------------------------------------------------------- available table
/** The position filter's choices: a G takes either guard, an F either forward. */
export const POSITIONS = ["PG", "SG", "G", "SF", "PF", "F", "C"] as const;
export type PositionFilter = (typeof POSITIONS)[number] | "";

export interface AvailableFilter {
  search: string;
  position: PositionFilter;
  /** FA only, waivers only, or both. */
  availability: "" | "FA" | "W";
  /** Hide players Yahoo lists as out (O, INJ, SUSP, NA, OFS). */
  healthy: boolean;
}

export const NO_FILTER: AvailableFilter = { search: "", position: "", availability: "", healthy: false };

const EXPAND: Partial<Record<PositionFilter, string[]>> = { G: ["PG", "SG", "G"], F: ["SF", "PF", "F"] };

export function playsPosition(positions: string[], position: PositionFilter): boolean {
  if (!position) return true;
  const want = EXPAND[position] ?? [position];
  return positions.some((p) => want.includes(p));
}

/** Folds accents so "porzingis" finds "Porziņģis". */
function fold(s: string): string {
  return s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
}

export function filterAvailable(rows: AvailableRow[], f: AvailableFilter): AvailableRow[] {
  const q = fold(f.search.trim());
  return rows.filter(
    (r) =>
      (!q || fold(r.player.name).includes(q) || fold(r.player.nba_team ?? "") === q) &&
      playsPosition(r.player.positions, f.position) &&
      (!f.availability || r.availability === f.availability) &&
      (!f.healthy || statusTone(r.player) !== "bad"),
  );
}

export type AvailableSortKey = "name" | "nba_team" | "positions" | "games_left" | "availability" | "status" | "pct_rostered" | "pct_rostered_change" | "pct_started" | "adds" | "drops";
export interface AvailableSort {
  key: AvailableSortKey;
  dir: "asc" | "desc";
}
/** Yahoo's own order: most rostered first. */
export const DEFAULT_AVAILABLE_SORT: AvailableSort = { key: "pct_rostered", dir: "desc" };
/** A first click sorts text A to Z and numbers high to low. */
export const TEXT_KEYS: AvailableSortKey[] = ["name", "nba_team", "positions", "availability", "status"];

function sortValue(r: AvailableRow, key: AvailableSortKey): number | string | null {
  switch (key) {
    case "name":
      return r.player.name;
    case "nba_team":
      return r.player.nba_team;
    case "positions":
      return r.player.positions.join(",") || null;
    case "availability":
      // Free agents first, then waivers by the date they clear.
      return r.availability === "FA" ? "0" : `1${r.clears ?? ""}`;
    case "status":
      return r.player.status;
    default:
      return r[key];
  }
}

/** Rows in sort order; missing values last either way, ties in Yahoo's order. */
export function sortAvailable(rows: AvailableRow[], sort: AvailableSort): AvailableRow[] {
  const sign = sort.dir === "asc" ? 1 : -1;
  return rows
    .map((r, i) => ({ r, i, v: sortValue(r, sort.key) }))
    .sort((a, b) => {
      if (a.v == null || b.v == null) return a.v == null && b.v == null ? a.i - b.i : a.v == null ? 1 : -1;
      const c = typeof a.v === "string" || typeof b.v === "string" ? String(a.v).localeCompare(String(b.v)) : a.v - b.v;
      return c !== 0 ? c * sign : a.i - b.i;
    })
    .map((x) => x.r);
}
