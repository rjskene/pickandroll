// The season view's pure helpers (#92): labels for ages, ownership and availability, the
// available table's filters and sort, the week projection's totals and odds (#93) and the moves'
// gains (#94). No React, so `npm test` runs them under Node.
import type {
  AvailableRow,
  Cat,
  MoveAdds,
  MoveCandidate,
  MoveHorizon,
  Rates,
  SeasonPlayer,
  SeasonRefresh,
  SeasonSummary,
  SeasonTeamRef,
  SeasonView,
  SeasonWeek,
  WeekStat,
} from "./api";

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
  /** One NBA team's players only; empty for every team. */
  nbaTeam: string;
  /** At least this many games this week (0: no floor). */
  minGames: number;
  /** At least this percent rostered (0: no floor). */
  minRostered: number;
}

export const NO_FILTER: AvailableFilter = {
  search: "",
  position: "",
  availability: "",
  healthy: false,
  nbaTeam: "",
  minGames: 0,
  minRostered: 0,
};

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

/** ``rows`` that pass ``f``; ``gamesThisWeek`` gives a row's games for the games floor (a row
 * without a count fails a floor above zero). */
export function filterAvailable(
  rows: AvailableRow[],
  f: AvailableFilter,
  gamesThisWeek: (r: AvailableRow) => number | null = (r) => r.games_left,
): AvailableRow[] {
  const q = fold(f.search.trim());
  return rows.filter(
    (r) =>
      (!q || fold(r.player.name).includes(q) || fold(r.player.nba_team ?? "") === q) &&
      playsPosition(r.player.positions, f.position) &&
      (!f.availability || r.availability === f.availability) &&
      (!f.healthy || statusTone(r.player) !== "bad") &&
      (!f.nbaTeam || r.player.nba_team === f.nbaTeam) &&
      (!f.minGames || (gamesThisWeek(r) ?? 0) >= f.minGames) &&
      (!f.minRostered || (r.pct_rostered ?? 0) >= f.minRostered),
  );
}

export type AvailableSortKey =
  | "name"
  | "nba_team"
  | "positions"
  | "games_left"
  | "availability"
  | "status"
  | "pct_rostered"
  | "pct_rostered_change"
  | "pct_started"
  | "adds"
  | "drops"
  // The week projection's columns (#93): games this week and the next three, each category's total.
  | "games"
  | "games_next3"
  // The moves' columns (#94): the best single move's gain on each horizon, and what the next
  // best drop costs on the table's horizon.
  | "gain_week"
  | "gain_three"
  | "next_price"
  | Cat;
export interface AvailableSort {
  key: AvailableSortKey;
  dir: "asc" | "desc";
}
/** Yahoo's own order: most rostered first. */
export const YAHOO_SORT: AvailableSort = { key: "pct_rostered", dir: "desc" };
/** The best move over the three weeks after this one first (#94); Yahoo's order until the
 * moves are valued. */
export const DEFAULT_AVAILABLE_SORT: AvailableSort = { key: "gain_three", dir: "desc" };
/** A first click sorts text A to Z and numbers high to low. */
export const TEXT_KEYS: AvailableSortKey[] = ["name", "nba_team", "positions", "availability", "status"];

/** A sort key's value from outside the row (the week projection's columns); undefined when the
 * key is the row's own. */
export type SortExtra = (r: AvailableRow, key: AvailableSortKey) => number | null | undefined;

function sortValue(r: AvailableRow, key: AvailableSortKey, extra?: SortExtra): number | string | null {
  const outside = extra?.(r, key);
  if (outside !== undefined) return outside;
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
    case "games_left":
    case "pct_rostered":
    case "pct_rostered_change":
    case "pct_started":
    case "adds":
    case "drops":
      return r[key];
    default:
      return null;
  }
}

/** Rows in sort order; missing values last either way, ties in Yahoo's order. */
export function sortAvailable(rows: AvailableRow[], sort: AvailableSort, extra?: SortExtra): AvailableRow[] {
  const sign = sort.dir === "asc" ? 1 : -1;
  return rows
    .map((r, i) => ({ r, i, v: sortValue(r, sort.key, extra) }))
    .sort((a, b) => {
      if (a.v == null || b.v == null) return a.v == null && b.v == null ? a.i - b.i : a.v == null ? 1 : -1;
      const c = typeof a.v === "string" || typeof b.v === "string" ? String(a.v).localeCompare(String(b.v)) : a.v - b.v;
      return c !== 0 ? c * sign : a.i - b.i;
    })
    .map((x) => x.r);
}

// ---------------------------------------------------------------- week projection (#93)
/** The Waivers table's horizons: the rest of this week (the streaming view) and the three weeks
 * after it (whether he is worth a roster spot). */
export type Horizon = "week" | "next3";
export const HORIZON_LABEL: Record<Horizon, string> = { week: "rest of this week", next3: "next 3 weeks" };

/** Games in a horizon: this week's from today, or the next three weeks' together. */
export function horizonGames(games: number[] | null | undefined, h: Horizon): number | null {
  if (!games || !games.length) return null;
  if (h === "week") return games[0] ?? null;
  const next = games.slice(1, 4);
  return next.length ? next.reduce((a, b) => a + b, 0) : null;
}

const PCT_PARTS: Partial<Record<Cat, [WeekStat, WeekStat]>> = { fg_pct: ["fgm", "fga"], ft_pct: ["ftm", "fta"] };

/** A player's projected categories over ``games`` games at ``rates`` per game: counting totals,
 * percentages as makes over attempts, a points league's fantasy points from its weights. */
export function projectedTotals(
  rates: Rates | null | undefined,
  games: number | null,
  cats: readonly Cat[],
  points?: Record<string, number> | null,
): Partial<Record<Cat, number | null>> | null {
  if (!rates || games == null) return null;
  const out: Partial<Record<Cat, number | null>> = {};
  for (const c of cats) {
    const parts = PCT_PARTS[c];
    if (c === "fpts") {
      out[c] = points ? Object.entries(points).reduce((t, [stat, w]) => t + w * (rates[stat as WeekStat] ?? 0) * games, 0) : null;
    } else if (parts) {
      const [made, att] = parts;
      // No games, no shots: a percentage over nothing is blank.
      out[c] = games > 0 && rates[att] ? rates[made] / rates[att] : null;
    } else {
      out[c] = rates[c as WeekStat] * games;
    }
  }
  return out;
}

export const isPct = (cat: Cat): boolean => cat === "fg_pct" || cat === "ft_pct";

/** A category's value in a cell: ".486" for a percentage, one decimal for a total. */
export function catValue(cat: Cat, v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "";
  return isPct(cat) ? v.toFixed(3).replace(/^0/, "") : v.toFixed(1);
}

/** "74%" for the odds of winning a category; "<1%" and ">99%" at the ends. */
export function oddsLabel(p: number): string {
  if (p < 0.005) return "<1%";
  if (p > 0.995) return ">99%";
  return `${Math.round(p * 100)}%`;
}

/** Likely won, likely lost, or open. */
export function oddsTone(p: number): "good" | "bad" | "" {
  return p >= 0.65 ? "good" : p <= 0.35 ? "bad" : "";
}

// ---------------------------------------------------------------- moves (#94)
/** The moves' horizon behind the table's: the rest of this week, or the three weeks after it. */
export const MOVE_HORIZON: Record<Horizon, MoveHorizon> = { week: "week", next3: "three" };

/** "+0.42" for a gain in expected categories, "−0.10" for a loss, "0.00" for neither; blank for
 * none. */
export function gainLabel(g: number | null | undefined, digits = 2): string {
  if (g == null || Number.isNaN(g)) return "";
  const r = Number(g.toFixed(digits));
  if (r === 0) return (0).toFixed(digits);
  return `${r > 0 ? "+" : "−"}${Math.abs(r).toFixed(digits)}`;
}

/** "Oct 22" for a day. */
export function dayLabel(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(`${iso}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** A gain worth a move, a loss, or neither. */
export function gainTone(g: number | null | undefined, min: number): "good" | "bad" | "" {
  if (g == null) return "";
  return g > min ? "good" : g < 0 ? "bad" : "";
}

/** A candidate's best single move on a horizon; null when none fits or he has no line. */
export function bestMove(c: MoveCandidate | undefined, h: MoveHorizon): MoveCandidate[MoveHorizon] {
  return c?.[h] ?? null;
}

/** The drop a candidate's drawer opens on: his best move's on the table's horizon, else the
 * other horizon's, else an open spot. */
export function openingDrop(c: MoveCandidate | undefined, h: MoveHorizon): number | null {
  const other: MoveHorizon = h === "week" ? "three" : "week";
  return (bestMove(c, h) ?? bestMove(c, other))?.drop ?? null;
}

/** "4 adds a week · 1 used this week · 3 left"; a count from a transactions page that may not
 * reach back to the week's start is a floor ("at least"), so what is left is a ceiling. */
export function addsNote(a: MoveAdds): string {
  if (a.limit == null) return "no weekly add limit";
  const used = `${a.complete ? "" : "at least "}${a.used} used this week`;
  return `${a.limit} adds a week · ${used} · ${a.complete ? "" : "at most "}${a.left ?? a.limit} left`;
}

/** Every player the view names, by Yahoo id: the pool, my roster and the league's rosters. */
export function playersById(s: Pick<SeasonView, "available" | "roster" | "rosters">): Map<number, SeasonPlayer> {
  const out = new Map<number, SeasonPlayer>();
  for (const rows of Object.values(s.rosters)) for (const r of rows) out.set(r.player.yahoo_id, r.player);
  for (const r of s.roster) out.set(r.player.yahoo_id, r.player);
  for (const r of s.available) out.set(r.player.yahoo_id, r.player);
  return out;
}
