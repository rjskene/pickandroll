// The season view's pure helpers (#92): labels for ages, ownership and availability, the
// available table's filters and sort, the week projection's totals and odds (#93) and the moves'
// gains (#94) with their rest of the season (#151), the strategy panel's (#110) and the
// scorecard's (#126). No React, so `npm test` runs them under Node.
import type {
  AddBasis,
  AllModesAnswer,
  AvailableRow,
  BestMove,
  BestSetLine,
  Cat,
  Comeback,
  FlagConfig,
  FlagInputs,
  FlagLevel,
  FlagSignalKey,
  HeldMove,
  ILRunLog,
  KeepRule,
  KeptPlayer,
  AutopilotView,
  LineupMode,
  LineupAlert,
  LineupDay,
  LineupPayload,
  LineupRunLog,
  LineupStepLog,
  MatchKind,
  MilpBlock,
  MoveAdds,
  MoveCandidate,
  MoveHorizon,
  MoveRef,
  MoveOutcome,
  MoveRoom,
  MoveRos,
  MovesPassLog,
  MovesStale,
  MovesSummary,
  MovesView,
  StartActiveRunLog,
  OutlookSummary,
  OutlookWeek,
  PlanStep,
  PlayerFlag,
  PlayerRos,
  PassTally,
  QueueEntry,
  QueueLeague,
  QueuePass,
  QueuePayload,
  Rates,
  RoutinePass,
  ScorecardMove,
  ScorecardToDate,
  ScorecardWeek,
  SeasonGuard,
  SeasonPlayer,
  SeasonRefresh,
  SeasonSummary,
  SeasonTeamRef,
  SeasonView,
  SeasonWeek,
  Stash,
  StrategyPayload,
  StrategyPoint,
  StrategySettings,
  StrategySource,
  StrategyWeightKey,
  StreamPlan,
  TradeMargin,
  TradePayload,
  TradePlayer,
  TradeSide,
  UnscoredReason,
  WeekPlan,
  WeekPlanBack,
  WeekPlans,
  WeekResult,
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
  // The table's horizon's best move to the season's end (#151).
  | "ros"
  // The breakout flag (#95): the sum of its four scores.
  | "flag"
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

// ---------------------------------------------------------------- matchup view (#116)
/** The matchup lines: favoured at 60% or better, an underdog at 40% or worse, else a toss-up. */
export const FAVOURED = 0.6;
export const UNDERDOG = 0.4;

export function leanTone(p: number): "good" | "bad" | "" {
  return p >= FAVOURED ? "good" : p <= UNDERDOG ? "bad" : "";
}

/** "+4.6%" for the matchup odds a player adds, "−0.3%" for odds he costs, "0.0%" for none. */
export function oddsGainLabel(x: number | null | undefined): string {
  return x == null || Number.isNaN(x) ? "" : `${gainLabel(x * 100, 1)}%`;
}

/** One paragraph of an explainer: a bold lead and its text. */
export interface Explained {
  lead: string;
  text: string;
}

/** What the Matchup view's Cats and Matchup columns mean (#226), behind the "i" on both headers:
 * with him minus without him for the rest of the week, each column's unit, why they disagree, the
 * signs and the opponent's side. A points league has no Cats column, so its explainer leaves the
 * Cats paragraphs out and its Matchup is the fantasy-points matchup's odds. */
export function matchupExplainer(points: boolean): Explained[] {
  const both: Explained = {
    lead: points ? "Matchup is \"with him minus without him\" for the rest of this week." : "Both columns are \"with him minus without him\" for the rest of this week.",
    text: "The model replays the week from today with the player gone, his starts going to the next starter by the daily lineup rules, and takes the difference. The week so far is already banked in both projections.",
  };
  const signs: Explained = {
    lead: "Signs and the other side.",
    text: "Green helps my team, red helps theirs. The opponent's rows are the same calculation from my side: what each of their players takes from me. A player with no start left shows nothing and is not re-projected; the opponent is projected for the current week only.",
  };
  if (points)
    return [
      both,
      {
        lead: "Matchup is the matchup win odds he adds, in percentage points.",
        text: "The odds are those of my projected fantasy points beating the opponent's this week. A player at +4.0% lifts those odds by four points.",
      },
      signs,
    ];
  return [
    both,
    {
      lead: "Cats is the expected categories won he adds.",
      text: "Each category's odds is the probability my projected final beats the opponent's, turnovers reversed; expected categories is the sum over the nine. A player at +0.40 is worth about four tenths of a category this week against this opponent.",
    },
    {
      lead: "Matchup is the matchup win odds he adds, in percentage points.",
      text: "The nine category odds are taken as independent, the number of categories won follows from them (a Poisson binomial), and the matchup is won with more categories won than lost, a tie counting half.",
    },
    {
      lead: "Why they disagree.",
      text: "Padding a category already won or lost by a wide margin adds Cats and little Matchup; swinging a close category adds Matchup. Matchup is this week's headline; Cats is what the moves and the strategy engine are judged on.",
    },
    signs,
  ];
}

/** The Matchup view's derived columns (#226): Cats (none in a points league) and Matchup, each
 * with its short tooltip in its unit; ``from`` is the first day the week is replayed from. Both
 * carry the explainer. */
export function matchupColumns(points: boolean, from: string | null | undefined): { key: "cats" | "matchup"; label: string; title: string }[] {
  const since = from ? ` from ${dayLabel(from)}` : "";
  const cats = { key: "cats" as const, label: "Cats", title: `expected categories he adds, in categories: the week with him less the week without him${since}` };
  const matchup = { key: "matchup" as const, label: "Matchup", title: `the matchup odds he adds, in percentage points of the matchup odds: the week with him less the week without him${since}` };
  return points ? [matchup] : [cats, matchup];
}

/** "5-3-1", the matchup so far as Yahoo counts it (won, lost, tied), or a points league's
 * "93.2–101.9"; mine first. */
export function matchupRecord(m: { score: [number, number] | null; tied: number | null }, scoring: SeasonSummary["scoring"]): string {
  const score = scoreLabel({ score: m.score, scoring });
  return m.score && scoring !== "points" && m.tied != null ? `${score}-${m.tied}` : score;
}

/** "3 days left" in the matchup, counting today when it is still to play. */
export function daysLeftLabel(days: number): string {
  return days <= 0 ? "no day left" : days === 1 ? "1 day left" : `${days} days left`;
}

// ---------------------------------------------------------------- season view (#116)
/** A week's chip: favoured, a toss-up or an underdog by its matchup odds against a named
 * opponent; the field when its pairs are not known (the playoffs); unread without odds. */
export function chipTone(w: Pick<OutlookWeek, "opponent" | "win">): "good" | "warn" | "bad" | "field" | "unread" {
  if (w.win == null) return "unread";
  if (w.opponent == null) return "field";
  return w.win >= FAVOURED ? "good" : w.win <= UNDERDOG ? "bad" : "warn";
}

/** The week a chip opens by default: next week, else the first left. */
export function defaultWeek(weeks: Pick<OutlookWeek, "week" | "this_week">[]): number | null {
  if (!weeks.length) return null;
  return (weeks[0].this_week ? weeks[1] ?? weeks[0] : weeks[0]).week;
}

/** "7.3 wins expected in the 19 regular weeks left", then the leans of the named weeks and
 * the weeks against the field; no wins when no week has odds (no roster faced read). */
export function outlookSummary(s: OutlookSummary): string[] {
  const weeks = `${s.weeks} regular week${s.weeks === 1 ? "" : "s"} left`;
  if (s.weeks > 0 && s.unread >= s.weeks) return [`${weeks}, none with odds yet: no roster faced was read`];
  const out = [`${s.expected_wins.toFixed(1)} wins expected in the ${weeks}`];
  const leans: [number, string, string][] = [
    [s.favoured, "favoured", "favoured"],
    [s.toss_up, "toss-up", "toss-ups"],
    [s.underdog, "underdog", "underdogs"],
  ];
  const named = leans.filter(([n]) => n > 0).map(([n, one, many]) => `${n} ${n === 1 ? one : many}`);
  if (named.length) out.push(named.join(" · "));
  if (s.field) out.push(`${s.field} against the field`);
  if (s.unread) out.push(`${s.unread} without odds, counted as none`);
  return out;
}

// ---------------------------------------------------------------- lineup view (#107)
/** "Mon 19": a day's column head. */
export function weekdayLabel(iso: string): string {
  const d = new Date(`${iso}T12:00:00`);
  return `${d.toLocaleDateString("en-US", { weekday: "short" })} ${d.getDate()}`;
}

/** A cell of the lineup grid: the recommended starter, or before the first day a change counts
 * Yahoo's; ``start`` when Yahoo's lineup has the recommended starter on the bench. */
export interface LineupCell {
  player: number | null;
  source: "recommended" | "yahoo" | null;
  start: boolean;
}

/** The lineup grid: a row per starting slot in the league's order, a cell per day. Yahoo's
 * starters fill a past day's slots of their kind in turn. */
export function lineupGrid(p: Pick<LineupPayload, "slots" | "days">): { slot: string; cells: LineupCell[] }[] {
  const nth = p.slots.map((slot, i) => p.slots.slice(0, i).filter((x) => x === slot).length);
  return p.slots.map((slot, i) => ({
    slot,
    cells: p.days.map((d): LineupCell => {
      if (d.recommended) {
        const k = d.recommended[i]?.player ?? null;
        return { player: k, source: "recommended", start: k != null && d.start.includes(k) };
      }
      if (d.yahoo) {
        const k = d.yahoo.slots.filter((x) => x.slot === slot)[nth[i]]?.player ?? null;
        return { player: k, source: "yahoo", start: false };
      }
      return { player: null, source: null, start: false };
    }),
  }));
}

/** A day's bench players who play that day: the recommended bench, or before the first day
 * Yahoo's. */
export function benchPlaying(d: LineupDay): number[] {
  const plays = new Set(d.playing ?? []);
  const bench = d.recommended ? (d.bench ?? []) : (d.yahoo?.slots ?? []).filter((x) => x.slot === "BN").map((x) => x.player);
  return bench.filter((k) => plays.has(k));
}

/** "daily lineups, a change counts today (the settings page)". */
export function ruleText(r: LineupPayload["rule"]): string {
  if (!r.changes) return "the lineup rule is not read: daily lineups assumed";
  const from = r.changes === "daily" ? `, a change counts ${r.from === "tomorrow" ? "tomorrow" : "today"}` : "";
  return `${r.changes} lineups${from}${r.source ? ` (${r.source})` : ""}`;
}

/** The week in a line: the games Yahoo's lineup as set loses and on which days, or none; the
 * days ahead not read. A week with none of its days read says so once. */
export function lineupSummary(p: Pick<LineupPayload, "summary" | "days">): string {
  const s = p.summary;
  const ahead = p.days.filter((d) => !d.past).length;
  if (ahead > 0 && s.unread.length === ahead) return "Yahoo's lineup is not read for these days: the recommended lineups alone";
  const days = s.differ.map(dayLabel).join(", ");
  const lost = s.lost > 0 ? `Yahoo's lineup as set loses ${s.lost} game${s.lost > 1 ? "s" : ""} (${days})` : "no game lost on the days read";
  return s.unread.length ? `${lost} · not read: ${s.unread.map(dayLabel).join(", ")}` : lost;
}

/** Where a player who could go to a held slot stands: "eligible, 1 open" or "eligible, IL full"
 * (the user decides whom to swap, #124); each kind named when there are several. */
export function heldEligibleText(slots: string[], open: Record<string, number>): string {
  const parts = slots.map((k) => {
    const n = open[k] ?? 0;
    if (n <= 0) return `${k} full`;
    return slots.length > 1 ? `${k} ${n} open` : `${n} open`;
  });
  return `eligible, ${parts.join(", ")}`;
}

/** An alert of the lineup route in words, a cleared occupant first. */
export function lineupAlertText(a: LineupAlert, name: (id: number) => string): string {
  if (a.kind === "cleared") {
    const drop = a.drop == null ? "" : a.drop === a.player ? "; activating him, he is the one to drop" : `; activating him drops ${name(a.drop)}`;
    return `${name(a.player)}'s status cleared (${a.status ?? "healthy"}) in ${a.slot}: Yahoo takes no add until he is activated${drop}.`;
  }
  if (a.kind === "unknown_status") return `${name(a.player)} is listed ${a.status}, a status the model does not know: no held slot takes him.`;
  if (a.kind === "held_lower_bound") {
    const kinds = Object.entries(a.slots).map(([k, n]) => `${n} ${k}`).join(", ");
    return `The held slots are at least ${kinds || "none"}, the most any roster read fills: the league's settings page is not read yet.`;
  }
  return "The lineup rule is not read: the lineups assume daily changes.";
}

// ---------------------------------------------------------------- the lineup executor (#170)
/** What the lineup executor does in the league, in a line. */
export function executorText(v: Pick<AutopilotView, "mode" | "stop">): string {
  if (v.mode.private) return "The private league is never touched: its lineups here are recommendations for you to set by hand.";
  if (v.stop) return "STOP is on (data/autopilot/STOP): no executor runs.";
  if (v.mode.mode === "off") return "Off: the extension leaves this league's lineup alone.";
  if (v.mode.mode === "dry_run") return "Dry run: on the team page, the extension logs what it would set and clicks nothing.";
  return "Live: on the team page, the extension sets the recommended lineup for today and tomorrow.";
}

/** Why live waits, or that the dry run has passed. */
export function liveText(l: AutopilotView["live"]): string {
  if (!l.ok) return `Live waits: ${l.reason ?? "the dry run"}.`;
  return `The dry run has passed: ${l.dry_run_days} days, ${l.checked_days} with steps that passed every check.`;
}

const RUN_OUTCOME: Record<LineupRunLog["outcome"], string> = {
  would_set: "would set",
  nothing_to_do: "nothing to do",
  skipped: "skipped",
  set: "set",
  failed: "failed",
  stopped: "stopped by STOP",
};
const TRIGGER: Record<LineupRunLog["trigger"] | StartActiveRunLog["trigger"], string> = {
  routine: "routine",
  routine_late: "late routine",
  routine_evening: "evening routine",
  routine_daily: "daily routine",
  panel: "side panel",
};

/** A run in a line: "05:02 · Sat 24 · routine: would set 2 moves", a live run's count the steps
 * it set. ``clock`` writes its time. */
export function runLine(r: LineupRunLog, clock: (iso: string) => string): string {
  const n = r.outcome === "set" ? r.steps.filter((s) => s.outcome === "set").length : r.steps.length;
  const moves = r.outcome === "would_set" || r.outcome === "set" ? ` ${n} move${n === 1 ? "" : "s"}` : "";
  const why = r.reason ? ` (${r.reason})` : "";
  const left = r.skipped.length ? `; ${r.skipped.length} left out, a game began` : "";
  return `${clock(r.at)} · ${weekdayLabel(r.day)} · ${TRIGGER[r.trigger]}: ${RUN_OUTCOME[r.outcome]}${moves}${why}${left}`;
}

/** A step in words: "Brooks BN → SF, Reed to BN: would set". */
export function stepText(s: LineupStepLog, name: (id: number) => string): string {
  const other = s.with != null ? `, ${name(s.with)} to ${s.from_slot}` : "";
  const outcome = s.outcome === "would_set" ? "would set" : s.outcome;
  return `${name(s.player)} ${s.from_slot} → ${s.to_slot}${other}: ${outcome}${s.reason ? ` (${s.reason})` : ""}`;
}

// ---------------------------------------------------------------- the moves executor (#171)
/** What the moves executor does in the league, in a line. */
export function movesExecutorText(v: Pick<MovesView, "mode" | "stop">): string {
  if (v.mode.private) return "The private league is never touched: its moves here are suggestions for you to make by hand.";
  if (v.stop) return "STOP is on (data/autopilot/STOP): no executor runs.";
  if (v.mode.mode === "off") return "Off: nothing of this league is queued; its moves stay suggestions.";
  if (v.mode.mode === "dry_run") return "Dry run: each morning's queue is built, and for each move due the extension reads Yahoo's add page and claims nothing.";
  return "Live: each move due is claimed on Yahoo's add page with its bid once its veto window is over.";
}

/** Why the moves executor's live waits, or that its dry run has passed. */
export function movesLiveText(l: MovesView["live"]): string {
  if (!l.ok) return `Live waits: ${l.reason ?? "the dry run"}.`;
  return `The dry run has passed: ${l.dry_run_days} days, ${l.checked_days} that read the add page.`;
}

/** "in 42 min", "in 2 h 5 min", "due": the time until an entry executes; blank for none. */
export function countdownLabel(at: string | null | undefined, now: number): string {
  const t = at ? Date.parse(at) : NaN;
  if (Number.isNaN(t)) return "";
  if (t <= now) return "due";
  const min = Math.ceil((t - now) / 60_000);
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h ? `in ${h} h${m ? ` ${m} min` : ""}` : `in ${m} min`;
}

const MOVE_OUTCOME: Record<MoveOutcome, string> = {
  would_claim: "would be claimed",
  claimed: "claimed",
  added: "added",
  skipped: "skipped",
  failed: "failed",
  gone: "gone: another team had him first",
};

const PASS_OUTCOME_WORD: Record<MoveOutcome, string> = {
  would_claim: "would claim",
  claimed: "claimed",
  added: "added",
  skipped: "skipped",
  failed: "failed",
  gone: "gone",
};

/** An entry's state: its outcome (and a placed claim's result, or its bid as the landed page read
 * it, #239), why it is not queued, struck, the latest pass's result (#200), or when it executes. */
export function queueStateText(e: QueueEntry, now: number): string {
  if (e.outcome) {
    const why = e.outcome_reason ?? (e.outcome === "claimed" && e.pass ? placedBidText(e.pass) || null : null);
    return `${MOVE_OUTCOME[e.outcome]}${why ? ` (${why})` : ""}${e.resolved ? `, ${e.resolved}` : ""}`;
  }
  if (!e.queued) return e.reason === "below the noise floor" && e.floor.below ? `below the ${e.floor.below} floor` : (e.reason ?? "not queued");
  if (e.struck) return "struck";
  if (e.pass) return passText(e.pass);
  const when = countdownLabel(e.executes_at, now);
  return when === "due" ? "due at the next pass" : `executes ${when}`;
}

/** A pass's result for its entry: "would claim · 9:32 AM CT", "skipped 9:32 AM CT: page not
 * read". */
export function passText(p: QueuePass): string {
  const clock = centralClock(p.at);
  const word = PASS_OUTCOME_WORD[p.outcome] ?? p.outcome;
  const head = p.outcome === "would_claim" ? `${word}${clock ? ` · ${clock}` : ""}` : `${word}${clock ? ` ${clock}` : ""}`;
  const why = p.reason ?? (placedBidText(p) || null);
  return why ? `${head}: ${why}` : head;
}

/** Whether a live claim's landed bid (#239) is another than the one it was placed for. */
function bidOff(p: Pick<QueuePass, "bid" | "bid_queued">): boolean {
  return p.bid != null && p.bid_queued != null && p.bid !== p.bid_queued;
}

/** A live claim's bid as its landed page read it (#239): "placed at $4", "bid not read" (null
 * means not read, never $0); blank for any other outcome, and for a bid other than the queue's,
 * whose reason says so. */
export function placedBidText(p: Pick<QueuePass, "outcome" | "bid" | "bid_queued">): string {
  if (p.outcome !== "claimed" || bidOff(p)) return "";
  return p.bid == null ? "bid not read" : `placed at $${p.bid}`;
}

const IL_WORDS: Record<ILRunLog["outcome"], string> = {
  would_move: "would move",
  moved: "moved",
  skipped: "IL move skipped",
  failed: "IL move failed",
  stopped: "IL move stopped by STOP",
};

/** An open-spot claim's IL move (#214), from the latest run naming the entry, else the queue's own
 * mark: "would move P5 to IL first", "moved P5 to IL 9:13 AM CT (dated Tue 28)", "IL move skipped
 * 9:13 AM CT: the page lists no IL row"; blank before one. */
export function ilText(e: Pick<QueueEntry, "date" | "held_move" | "il" | "il_pass">, name: (id: number) => string): string {
  const r = e.il_pass ?? (e.il ? { ...e.il, player: null, to_slot: null, dated: null } : null);
  if (!r) return "";
  const k = r.player ?? e.held_move?.player;
  const who = k != null ? name(k) : "the held player";
  const slot = r.to_slot ?? e.held_move?.slot ?? "IL";
  const clock = centralClock(r.at);
  const dated = r.dated && r.dated !== e.date ? ` (dated ${weekdayLabel(r.dated)})` : "";
  if (r.outcome === "would_move") return `would move ${who} to ${slot} first${dated}`;
  if (r.outcome === "moved") return `moved ${who} to ${slot}${clock ? ` ${clock}` : ""}${dated}`;
  const head = `${IL_WORDS[r.outcome] ?? r.outcome}${clock && r.outcome !== "stopped" ? ` ${clock}` : ""}`;
  return r.reason ? `${head}: ${r.reason}` : head;
}

/** An entry's state with its IL move after it (#214): "skipped 9:14 AM CT: … · moved P5 to IL 9:13
 * AM CT". */
export function queueStateLine(e: QueueEntry, now: number, name: (id: number) => string): string {
  const waits = e.queued && !e.struck && !e.outcome ? waitText(e.waits, name) : "";
  return [waits || queueStateText(e, now), e.queued && !e.struck ? ilText(e, name) : ""].filter(Boolean).join(" · ");
}

/** What a week plan's step waits for (#221 part 2): "waits for step 1 to land (Brooks)"; blank for
 * nothing. */
export function waitText(w: Pick<NonNullable<QueueEntry["waits"]>, "text" | "add"> | null | undefined, name: (id: number) => string): string {
  if (!w) return "";
  return w.add != null ? `${w.text} (${name(w.add)})` : w.text;
}

/** A week plan's step on the queue (#221 part 2): "step 2 of 3"; blank for a move of the set. */
export function planStepTag(e: Pick<QueueEntry, "plan">): string {
  return e.plan ? `step ${e.plan.step} of ${e.plan.steps}` : "";
}

/** The state's tone: good for a claim (a pass that would claim, or one placed), bad for a failure
 * or a claim placed at another bid than the queue's. */
export function queueStateTone(e: QueueEntry): "good" | "bad" | "" {
  const o = e.outcome ?? (e.queued && !e.struck ? e.pass?.outcome : null);
  // A claim placed at another bid than the queue's stays claimed, in the bad tone (#239).
  if (o === "claimed" && e.pass?.outcome === "claimed" && bidOff(e.pass)) return "bad";
  if (o === "would_claim" || o === "claimed" || o === "added") return "good";
  return o === "failed" ? "bad" : "";
}

/** The state's hover: "routine pass at 9:32 AM CT, extension 0.7.0"; blank without a pass. */
export function passTitle(e: Pick<QueueEntry, "pass">): string {
  const p = e.pass;
  if (!p) return "";
  const clock = centralClock(p.at);
  return `${p.trigger ? TRIGGER[p.trigger] : "a"} pass${clock ? ` at ${clock}` : ""}${p.extension ? `, extension ${p.extension}` : ""}`;
}

/** The day's pass results in a line: "13 would claim · 7 skipped · last pass 9:35 AM CT", the
 * counts at zero left out; blank without any. */
export function passTally(t: PassTally | null | undefined): string {
  if (!t) return "";
  const parts: [number, string][] = [
    [t.would_claim, "would claim"],
    [t.claimed, "claimed"],
    [t.skipped, "skipped"],
    [t.gone, "gone"],
    [t.failed, "failed"],
  ];
  const clock = centralClock(t.last);
  return [...parts.filter(([n]) => n).map(([n, w]) => `${n} ${w}`), clock ? `last pass ${clock}` : null].filter(Boolean).join(" · ");
}

/** "$2 claim", "$0 claim (the $2 bid struck)", "free agent, $0". */
export function bidLabel(e: Pick<QueueEntry, "availability" | "bid" | "bid_struck">): string {
  if (e.availability === "FA") return "free agent, $0";
  if (e.bid_struck) return `$0 claim (the $${e.bid.amount} bid struck)`;
  return `$${e.bid.amount} claim`;
}

/** "Brooks for Reed", "Brooks after Hurt to IL", "Brooks (free: open spot)": the move in words,
 * by its basis (#187). An entry logged before the basis with no drop says only that. */
export function queueMoveText(e: Pick<QueueEntry, "add" | "drop" | "basis" | "held_move" | "held_drop" | "plan">, name: (id: number) => string): string {
  const step = planStepTag(e);
  const tail = step ? ` (${step} of the week plan)` : "";
  if (e.drop == null && e.basis == null) return `${name(e.add)} with no drop${tail}`;
  return `${name(e.add)} ${basisPhrase(addBasis({ drop: e.drop, held: e.held_move, held_drop: e.held_drop }, name))}${tail}`;
}

/** The floor and the typical gain the league's entries were judged with, in a line. */
export function queueFloorLine(r: Pick<QueueLeague, "floor" | "typical" | "scoring">): string {
  const f = r.floor;
  if (!f || !r.typical) return "";
  const units = r.scoring === "points" ? "points" : "expected categories";
  const scored =
    f.scored == null
      ? `; the scorecard's spread joins it once ${f.needs} moves are scored (${f.moves} so far)`
      : ` and the scorecard's spread of ${f.scored.toFixed(1)} in value units over ${f.moves} moves`;
  return `Floor: a gain of ${f.plan} ${units} over the three weeks${scored}. Bids scale by a typical gain of ${r.typical.value} (${r.typical.from}).`;
}

const PASS_OUTCOME: Record<MovesPassLog["outcome"], string> = {
  would_claim: "would claim",
  nothing_due: "nothing due",
  skipped: "skipped",
  claimed: "claimed",
  failed: "failed",
  stopped: "stopped by STOP",
};

/** A pass in a line: "9:00 AM · Thu 23 · routine: would claim 2 (1 gone)". ``clock`` writes its time. */
export function passLine(r: MovesPassLog, clock: (iso: string) => string): string {
  const done = r.entries.filter((e) => e.outcome === "would_claim" || e.outcome === "claimed" || e.outcome === "added").length;
  const others = (["skipped", "failed", "gone"] as const).map((k) => [k, r.entries.filter((e) => e.outcome === k).length] as const).filter(([, n]) => n);
  const count = done ? ` ${done}` : "";
  const rest = others.length ? ` (${others.map(([k, n]) => `${n} ${k}`).join(", ")})` : "";
  return `${clock(r.at)} · ${weekdayLabel(r.day)} · ${TRIGGER[r.trigger]}: ${PASS_OUTCOME[r.outcome]}${count}${rest}${r.reason ? ` (${r.reason})` : ""}`;
}

/** An IL run in a line (#214): "9:13 AM · Tue 27 · routine: would move P5 to IL", "… · late: IL
 * move skipped (the page lists no IL row)". ``clock`` writes its time. */
export function ilLine(r: ILRunLog, clock: (iso: string) => string, name: (id: number) => string): string {
  const who = r.player != null ? name(r.player) : "the held player";
  const dated = r.dated && r.dated !== r.day ? ` (dated ${weekdayLabel(r.dated)})` : "";
  const what = r.outcome === "would_move" || r.outcome === "moved" ? `${IL_WORDS[r.outcome]} ${who} to ${r.to_slot ?? "IL"}${dated}` : IL_WORDS[r.outcome];
  return `${clock(r.at)} · ${weekdayLabel(r.day)} · ${TRIGGER[r.trigger]}: ${what}${r.reason ? ` (${r.reason})` : ""}`;
}

const SA_WORDS: Record<StartActiveRunLog["outcome"], string> = {
  would_start: "would start active players for the rest of the week",
  started: "started active players",
  already: "already optimized",
  skipped: "Start Active skipped",
  failed: "Start Active failed",
  stopped: "Start Active stopped by STOP",
};

/** A Start Active run in a line (#215): "5:02 AM · Wed 21 · daily routine: started active players,
 * Rest of Week 2 (Tue, Oct 27 - Sun, Nov 01) · 6 lineups updated". ``clock`` writes its time. */
export function startActiveLine(r: StartActiveRunLog, clock: (iso: string) => string): string {
  const row = r.rest_of_week;
  const week = r.outcome === "started" && row?.label ? `, ${row.label}${row.range ? ` (${row.range})` : ""}` : "";
  const why = r.reason ? ` (${r.reason})` : "";
  const words = r.message ? ` · ${r.message}` : "";
  return `${clock(r.at)} · ${weekdayLabel(r.day)} · ${TRIGGER[r.trigger]}: ${SA_WORDS[r.outcome]}${week}${why}${words}`;
}

const SA_TALLY: [StartActiveRunLog["outcome"], string][] = [
  ["started", "started"],
  ["already", "already optimized"],
  ["would_start", "would start"],
  ["skipped", "skipped"],
  ["failed", "failed"],
];

/** "Start Active: 3 started, 1 would start": the leagues' latest runs of the day (#215); blank
 * before one. */
export function startActiveTally(runs: Record<string, StartActiveRunLog> | undefined): string {
  const all = Object.values(runs ?? {});
  const parts = SA_TALLY.map(([k, w]) => [all.filter((r) => r.outcome === k).length, w] as const).filter(([n]) => n);
  return parts.length ? `Start Active: ${parts.map(([n, w]) => `${n} ${w}`).join(", ")}` : "";
}

/** The landing's line for today's queue across the leagues. */
export function queueFoldLine(q: QueuePayload): string {
  const time = `executes from ${q.settings.in_force} CT`;
  if (q.stop) return "STOP is on (data/autopilot/STOP): nothing executes";
  if (!q.built.length) return `no queue built today: the morning routine builds it · ${time}`;
  const live = q.entries.filter((e) => e.queued && !e.struck && !e.outcome);
  const struck = q.entries.filter((e) => e.struck).length;
  const done = q.entries.filter((e) => e.outcome === "would_claim" || e.outcome === "claimed" || e.outcome === "added").length;
  const leagues = new Set(live.map((e) => e.league)).size;
  const unsolved = q.leagues.filter((l) => l.status === "not_solved").length;
  const failed = q.leagues.filter((l) => l.status === "failed").length;
  const running = q.active ? `pass running · ${passLeague(q.active)} of ${q.active.leagues.total}` : null;
  return [
    `${live.length} queued${live.length ? ` in ${leagues} league${leagues === 1 ? "" : "s"}` : ""}`,
    running,
    struck ? `${struck} struck` : null,
    done ? `${done} executed` : null,
    passTally(q.passes) || null,
    startActiveTally(q.start_active) || null,
    unsolved ? `${unsolved} not solved today` : null,
    failed ? `${failed} not read` : null,
    time,
  ]
    .filter(Boolean)
    .join(" · ");
}

// ---------------------------------------------------------------- a routine's pass, live (#201)
const PASS_RESULT_WORDS: Record<string, string> = {
  would_claim: "would claim",
  claimed: "claimed",
  skipped: "skipped",
  gone: "gone",
  failed: "failed",
  would_set: "would set",
  set: "set",
  nothing_to_do: "nothing to do",
};
const PASS_TRIGGER_WORDS: Record<RoutinePass["trigger"], string> = { routine: "Morning", routine_late: "Late", routine_evening: "Evening" };
/** How long a closed pass's line stays on the Queue screen. */
export const PASS_END_SHOWN_MS = 10 * 60_000;

/** The league a running pass is on, by its place in the pass's order: the one it is opening, else
 * the count done. */
export function passLeague(p: Pick<RoutinePass, "leagues" | "current">): number {
  const at = p.current ? p.leagues.order.indexOf(p.current.league) : -1;
  return at >= 0 ? at + 1 : p.leagues.done;
}

/** "6 would claim, 2 skipped": a pass's results, the counts above zero in the record's order. */
export function passResults(p: Pick<RoutinePass, "results">, sep = ", "): string {
  return Object.entries(p.results)
    .filter(([, n]) => n)
    .map(([k, n]) => `${n} ${PASS_RESULT_WORDS[k] ?? k}`)
    .join(sep);
}

const IL_RESULT_WORDS: Record<keyof NonNullable<RoutinePass["il"]>, string> = {
  would_move: "would move to IL",
  moved: "moved to IL",
  skipped: "IL skipped",
  failed: "IL failed",
};

const SA_RESULT_WORDS: Record<keyof NonNullable<RoutinePass["start_active"]>, string> = {
  would_start: "would start active",
  started: "started active",
  already: "already optimized",
  skipped: "Start Active skipped",
  failed: "Start Active failed",
};

/** "1 moved to IL, 1 IL skipped, 2 started active": a moves pass's IL runs (#214) and Start
 * Active runs (#215), the counts above zero; blank before one. */
export function passIL(p: Pick<RoutinePass, "il" | "start_active">, sep = ", "): string {
  const il = Object.entries(p.il ?? {}).map(([k, n]) => [n, IL_RESULT_WORDS[k as keyof typeof IL_RESULT_WORDS] ?? k] as const);
  const sa = Object.entries(p.start_active ?? {}).map(([k, n]) => [n, SA_RESULT_WORDS[k as keyof typeof SA_RESULT_WORDS] ?? k] as const);
  return [...il, ...sa]
    .filter(([n]) => n)
    .map(([n, w]) => `${n} ${w}`)
    .join(sep);
}

/** The Queue screen's bar while a routine's pass runs: "Morning moves pass running · league 5 of
 * 12 · 8 of 20 checked · 6 would claim, 2 skipped"; "Late lineup pass running · 7 of 12 team
 * pages". */
export function passBar(p: RoutinePass): string {
  const head = `${PASS_TRIGGER_WORDS[p.trigger]} ${p.kind} pass running`;
  const at = passLeague(p);
  const parts =
    p.kind === "moves"
      ? [`league ${at} of ${p.leagues.total}`, p.entries ? `${p.entries.done}${p.entries.total != null ? ` of ${p.entries.total}` : ""} checked` : null]
      : [`${at} of ${p.leagues.total} team pages`];
  return [head, ...parts, passResults(p) || null, passIL(p) || null].filter(Boolean).join(" · ");
}

/** The line a closed pass leaves on the Queue screen for ten minutes: "moves pass done 9:35 AM CT ·
 * 13 would claim · 7 skipped", "… stale …" for one that went quiet; blank after. */
export function passEndLine(p: RoutinePass | null | undefined, now: number): string {
  if (!p || !p.ended || !p.end) return "";
  const ended = Date.parse(p.ended);
  if (Number.isNaN(ended) || now - ended > PASS_END_SHOWN_MS) return "";
  return [`${p.kind} pass ${p.end} ${centralClock(p.ended)}`, passResults(p, " · ") || null, passIL(p, " · ") || null, passHeld(p) || null, p.summary].filter(Boolean).join(" · ");
}

/** The week plan's steps a pass left held on an earlier step (#221 part 2): "1 step held: waits for
 * step 1 to land"; blank for none. */
export function passHeld(p: Pick<RoutinePass, "held">): string {
  const held = Object.values(p.held ?? {});
  if (!held.length) return "";
  const texts = [...new Set(held.map((h) => h.text))];
  return `${held.length} ${held.length === 1 ? "step" : "steps"} held: ${texts.join("; ")}`;
}

/** Whether a running pass is checking ``e`` now: it is the entry being opened, and no post about it
 * has landed since the opening. */
export function checkingNow(e: Pick<QueueEntry, "id" | "pass">, p: RoutinePass | null | undefined): boolean {
  if (!p?.current?.entry || p.current.entry !== e.id) return false;
  const since = Date.parse(p.current.since);
  const at = e.pass?.at ? Date.parse(e.pass.at) : NaN;
  return Number.isNaN(at) || at < since;
}

/** The Queue screen's and the landing's poll: every 3 s while a routine's pass runs, else a minute. */
export function queuePoll(q: Pick<QueuePayload, "active"> | undefined): number {
  return q?.active ? 3_000 : 60_000;
}

// ---------------------------------------------------------------- the Queue screen (#194)
/** A player the day's queue names, by id; "player 7" for one it does not. */
export function queueNamer(q: Pick<QueuePayload, "names">): (id: number) => string {
  return (id) => q.names?.[String(id)] ?? `player ${id}`;
}

/** The day's queued entries of every league (queued, struck or executed) in the order they
 * execute: by the time (none last), then the league's rank, then the league. */
export function queueOrder(entries: QueueEntry[]): QueueEntry[] {
  const at = (e: QueueEntry) => {
    const t = e.executes_at ? Date.parse(e.executes_at) : NaN;
    return Number.isNaN(t) ? Infinity : t;
  };
  return entries
    .filter((e) => e.queued)
    .sort((a, b) => at(a) - at(b) || (a.rank ?? Infinity) - (b.rank ?? Infinity) || a.league.localeCompare(b.league));
}

/** The entries the build left out, by league, then the gain (most first). */
export function notQueued(entries: QueueEntry[]): QueueEntry[] {
  return entries.filter((e) => !e.queued).sort((a, b) => a.league.localeCompare(b.league) || (b.gain ?? -Infinity) - (a.gain ?? -Infinity));
}

const ROW_STATUS: Record<QueueLeague["status"], string> = {
  queued: "",
  not_solved: "not solved today",
  off: "the moves executor is off",
  private: "the private league is never touched",
  failed: "not read",
};

/** Why a league's chip shows none queued: the row's own reason when it did not build (not solved,
 * off, private, failed); for a league that built and queued nothing, the reason most of its
 * entries share, else "nothing queued"; blank for one that queued. */
export function stripReason(row: QueueLeague, entries: QueueEntry[]): string {
  if (row.status !== "queued") return row.reason ?? ROW_STATUS[row.status];
  const mine = entries.filter((e) => e.league === row.league);
  if (mine.some((e) => e.queued)) return "";
  const counts = new Map<string, number>();
  for (const e of mine) {
    const why = queueStateText(e, 0);
    counts.set(why, (counts.get(why) ?? 0) + 1);
  }
  let top = "";
  for (const [why, n] of counts) if (!top || n > counts.get(top)!) top = why;
  return top || "nothing queued";
}

// ---------------------------------------------------------------- one switch (#205)
const MODE_ORDER: LineupMode[] = ["live", "dry_run", "off"];
export const MODE_WORDS: Record<LineupMode, string> = { off: "off", dry_run: "dry run", live: "live" };
type SwitchRow = Pick<QueueLeague, "league" | "status" | "scoring" | "mode" | "live">;

/** The leagues the Queue screen's one switch sets: every row but the private one, the points
 * leagues the landing hides among them. */
export function switchRows<T extends Pick<QueueLeague, "status">>(rows: T[]): T[] {
  return rows.filter((r) => r.status !== "private");
}

/** "all 12 public leagues, the 3 points leagues the landing hides among them": what the one
 * switch covers, the points leagues said. */
export function switchScope(rows: Pick<QueueLeague, "status" | "scoring">[]): string {
  const mine = switchRows(rows);
  const points = mine.filter((r) => r.scoring === "points").length;
  const all = mine.length === 1 ? "the 1 public league" : `all ${mine.length} public leagues`;
  return points ? `${all}, the ${points} points league${points === 1 ? "" : "s"} the landing hides among them` : all;
}

/** The modes in force across the public leagues: "12 dry run", "9 live · 3 dry run". */
export function modesWord(rows: Pick<QueueLeague, "status" | "mode">[]): string {
  const mine = switchRows(rows);
  return MODE_ORDER.map((m) => [m, mine.filter((r) => r.mode === m).length] as const)
    .filter(([, n]) => n)
    .map(([m, n]) => `${n} ${MODE_WORDS[m]}`)
    .join(" · ");
}

/** The mode every public league is in; null when they differ, or there is none. */
export function commonMode(rows: Pick<QueueLeague, "status" | "mode">[]): LineupMode | null {
  const modes = new Set(switchRows(rows).map((r) => r.mode));
  return modes.size === 1 ? [...modes][0] : null;
}

/** The public leagues not live: those the guard lets go live now, and those it keeps. */
export function liveSplit<T extends SwitchRow>(rows: T[]): { ready: T[]; waiting: T[] } {
  const rest = switchRows(rows).filter((r) => r.mode !== "live");
  return { ready: rest.filter((r) => r.live?.ok), waiting: rest.filter((r) => !r.live?.ok) };
}

/** The one switch's confirm line on live: "Switch all 12 to live: each claims its due moves on
 * Yahoo's add page with its bid." Leagues already live, or that their guard keeps, are said. */
export function allLiveLine(rows: SwitchRow[]): string {
  const mine = switchRows(rows);
  const { ready, waiting } = liveSplit(rows);
  const points = ready.filter((r) => r.scoring === "points").length;
  const among = points ? `, the ${points} points league${points === 1 ? "" : "s"} among them` : "";
  const head = ready.length === mine.length ? `Switch all ${ready.length} to live${among}` : `Switch ${ready.length} of the ${mine.length} to live${among}`;
  const already = mine.length - ready.length - waiting.length;
  const rest = [
    waiting.length ? `${waiting.length} keep${waiting.length === 1 ? "s" : ""} ${waiting.length === 1 ? "its" : "their"} mode: live waits` : "",
    already ? `${already} already live` : "",
  ].filter(Boolean);
  return `${head}: each claims its due moves on Yahoo's add page with its bid${rest.length ? `; ${rest.join("; ")}` : ""}.`;
}

/** The hover on the one switch's live: the guard's reasons for the leagues it keeps. */
export function allLiveTitle(rows: SwitchRow[], title: (league: string) => string): string {
  const { ready, waiting } = liveSplit(rows);
  if (!waiting.length) return ready.length ? "The dry run has passed in every league not live." : "Every public league is live.";
  return `Live waits in ${waiting.map((r) => `${title(r.league)} (${r.live?.reason ?? "the dry run"})`).join(", ")}.`;
}

/** The leagues the one switch left in their mode, each with why. */
export function keptLines(a: AllModesAnswer, title: (league: string) => string): string[] {
  return a.leagues.filter((x) => !x.ok).map((x) => `${title(x.league)} stays ${MODE_WORDS[x.mode]}: ${x.reason ?? "refused"}`);
}

/** The adds left in the week holding ``today`` as the build read them; null for no limit, or a
 * week it did not read. */
export function addsThisWeek(row: Pick<QueueLeague, "adds_left">, today: string): number | null {
  return row.adds_left?.find((w) => w.start <= today && today <= w.end)?.adds ?? null;
}

/** How often the Moves card asks again (#240): every 3 s while its answer is stale, for at most
 * 120 s from the first stale one (then not until the next refresh); otherwise every minute. */
export const MOVES_POLL_MS = 60_000;
export const STALE_POLL_MS = 3_000;
export const STALE_CAP_MS = 120_000;

/** The Moves card's refetch interval (#240): ``since`` is when its answer first came back stale,
 * null while it is fresh. */
export function movesPoll(stale: boolean, since: number | null, now: number): number | false {
  if (!stale) return MOVES_POLL_MS;
  return since != null && now - since >= STALE_CAP_MS ? false : STALE_POLL_MS;
}

/** The Moves card's line while its answer is stale (#240): solving, or, once the card stopped
 * asking, still solving with the answer's build time. */
export function staleLine(stale: MovesStale, capped: boolean, clock: (iso: string | null) => string): string {
  const built = stale.built_at ? ` (this answer built ${clock(stale.built_at)})` : "";
  return capped ? `still solving${built}: refresh to look again` : `solving: ${stale.reason.replace(/; solving$/, "")}${built}`;
}

/** "7:00 AM CT": an instant on the Central clock the execute time is set on (#193); blank for
 * none. */
export function centralClock(iso: string | null | undefined): string {
  const t = iso ? Date.parse(iso) : NaN;
  if (Number.isNaN(t)) return "";
  return `${new Date(t).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/Chicago" })} CT`;
}

/** An entry's flag in the Queue card's words: "strong breakout", "breakout", or blank. */
export function queueFlagWord(flag: QueueEntry["flag"]): string {
  return flag === "must-add" ? "strong breakout" : flag && flag !== "watch" ? "breakout" : "";
}

/** The strip's order: the private league first, then the rest by name (its id without one). */
export function stripOrder<T extends Pick<QueueLeague, "league" | "status">>(rows: T[], title: (league: string) => string): T[] {
  return [...rows].sort((a, b) => Number(b.status === "private") - Number(a.status === "private") || title(a.league).localeCompare(title(b.league)));
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

/** The drops held players' returns force, each player's earliest over the horizons: "From Nov 2,
 * Ayton goes when Brooks returns." (#97); null for none. */
export function comebackText(lists: (Comeback[] | undefined)[], name: (id: number) => string): string | null {
  const first = new Map<number, Comeback>();
  for (const c of lists.flatMap((l) => l ?? [])) {
    const seen = first.get(c.player);
    if (!seen || c.from < seen.from) first.set(c.player, c);
  }
  if (!first.size) return null;
  const parts = [...first.values()]
    .sort((a, b) => a.from.localeCompare(b.from) || a.player - b.player)
    .map((c) =>
      c.drop === c.player
        ? `from ${dayLabel(c.from)}, ${name(c.player)} goes on return`
        : `from ${dayLabel(c.from)}, ${name(c.drop)} goes when ${name(c.player)} returns`,
    );
  const text = parts.join("; ");
  return `${text[0].toUpperCase()}${text.slice(1)}.`;
}

/** Whom an add goes in for: his drop, the held-slot move that makes room ("Brooks to IL"), or
 * an open spot (#124). */
export function forText(x: { drop: number | null; held?: HeldMove | null }, name: (id: number | null) => string): string {
  return x.drop == null && x.held ? `${name(x.held.player)} to ${x.held.slot}` : name(x.drop);
}

/** An add's basis in words (#187): the kind, its text, the For column's cell (a drop's name
 * alone: the header says "For") and the rule that applied, for a title. */
export interface Basis {
  kind: AddBasis;
  text: string;
  cell: string;
  title: string;
}

export function addBasis(x: { drop: number | null; held?: HeldMove | null; held_drop?: HeldMove | null }, name: (id: number) => string): Basis {
  if (x.drop != null && x.held_drop) {
    const who = name(x.drop);
    const slot = x.held_drop.slot;
    const moved = x.held ? `, ${name(x.held.player)} to ${x.held.slot}` : "";
    const room = x.held
      ? `${name(x.held.player)} moves into the freed slot and gives the add his active spot`
      : "an active spot is open for the add";
    const title = `a churn (#221): ${who} leaves ${slot}, dropped first on his own; ${room}. Offered only for a free agent, or when ${who} is worth nothing net of his return`;
    return { kind: "churn", text: `for ${who} from ${slot}${moved}`, cell: `${who} (${slot})${moved}`, title };
  }
  if (x.drop != null) {
    const who = name(x.drop);
    const title = "a drop: no active spot is open, and no held move makes room or it is worth less than this drop (the held move is priced against every drop)";
    return { kind: "drop", text: `for ${who}`, cell: who, title };
  }
  if (x.held) {
    const who = name(x.held.player);
    const text = `after ${who} to ${x.held.slot}`;
    const title = `${who}'s status fits the open ${x.held.slot} slot: he moves there for the add, and his return sends the weakest active player then`;
    return { kind: "held", text, cell: text, title };
  }
  return { kind: "open", text: "free: open spot", cell: "free: open spot", title: "an active spot is open: no drop" };
}

/** The basis after an add's name: "for Reed", "after Hurt to IL", "(free: open spot)". */
export function basisPhrase(b: Basis): string {
  return b.kind === "open" ? `(${b.text})` : b.text;
}

/** The Moves card's room (#187): "1 open spot · IL open: 1" when any room is open; else
 * "roster full, IL full" (with who waits for it) or "roster full, no held slots". */
export function roomNote(room: MoveRoom, name: (id: number) => string): string {
  const kinds = Object.entries(room.held_open);
  const open = [
    ...(room.open_spots > 0 ? [`${room.open_spots} open spot${room.open_spots === 1 ? "" : "s"}`] : []),
    ...kinds.filter(([, n]) => n > 0).map(([k, n]) => `${k} open: ${n}`),
  ];
  if (open.length) return open.join(" · ");
  if (!kinds.length) return "roster full, no held slots";
  const waits = room.eligible.length ? ` (${room.eligible.map(name).join(", ")} ${room.eligible.length === 1 ? "waits" : "wait"})` : "";
  return `roster full, ${kinds.map(([k]) => `${k} full`).join(", ")}${waits}`;
}

/** The line under a recommended set the season guard changed (#164): "The season guard held back
 * a set that gains +1.50 on the week but costs the season −95.0; this one forgoes 1.15." A total
 * with a move without a season line says so; null when the guard held nothing back. */
export function seasonGuardLine(
  guard: SeasonGuard | null | undefined,
  key: MoveHorizon,
  scoring: string | null | undefined,
): string | null {
  if (!guard?.held_back) return null;
  const on = key === "week" ? "on the week" : "over the three weeks";
  const partial = guard.ros.partial ? " (a partial total: a move without a season line counts as zero)" : "";
  return (
    `The season guard held back a set that gains ${gainLabel(guard.gain[key])} ${on} but costs the season ` +
    `${rosLabel(guard.ros, scoring)}${partial}; this one forgoes ${Math.abs(guard.forgone[key]).toFixed(2)}.`
  );
}

/** The set the season guard held back, each move flagged as the log flags it (#164): "add Brooks
 * for Grant (season-costly, −95.0)"; null when it held nothing back. Never a recommendation. */
export function seasonGuardMoves(
  guard: SeasonGuard | null | undefined,
  name: (id: number | null) => string,
  scoring: string | null | undefined,
): string | null {
  if (!guard?.held_back) return null;
  return guard.moves
    .map((x) => {
      const flags = [x.season_costly ? "season-costly" : null, x.ros?.value != null ? rosLabel(x.ros, scoring) : null].filter(Boolean);
      return `add ${name(x.add)}${x.drop == null && !x.held ? "" : ` for ${forText(x, name)}`}${flags.length ? ` (${flags.join(", ")})` : ""}`;
    })
    .join("; ");
}

/** The week's streaming plan to show (#136): only a recommended one. */
export function shownPlan(plan: StreamPlan | null | undefined): StreamPlan | null {
  return plan?.recommended && plan.steps.length ? plan : null;
}

/** The week plans to show (#221 part 2): none with no day left or no plan with a step. */
export function shownWeekPlans(wp: WeekPlans | null | undefined): WeekPlan[] {
  return (wp?.plans ?? []).filter((w) => w.steps.length || w.backs.length);
}

/** The Week plans section's tooltip (#221 part 2): the limits, plan 1's rule and the floor. Plan 1
 * is the week's recommended set, whatever its steps; the searched plans keep the limit (the
 * master's ruling of 2026-10-29). */
export function weekPlansTitle(wp: Pick<WeekPlans, "limits" | "seconds" | "floor">, units: string): string {
  const l = wp.limits;
  return (
    `plan 1 is the week's recommended set; the searched plans are at most ${l.steps} steps, up to ${l.plans} plans over the rest of the week, ` +
    `searched ${l.beam} wide and the best ${l.exact} valued exactly in ${wp.seconds.toFixed(1)} s; a searched plan is plan 1 only when it beats the set's week by the floor, ${wp.floor} ${units}; ` +
    "plans with the same adds on the same days are one, the best week kept; recommended, a heuristic"
  );
}

/** A week plan's head: "Plan 1 · the week's set · +0.42 this week, +0.10 over three weeks", the
 * queue's plan marked "queued in place of the three weeks' set". */
export function weekPlanHead(w: WeekPlan, i: number, queued: boolean): string {
  const parts = [`Plan ${i + 1}`, w.source === "set" ? "the week's set" : null, `${gainLabel(w.total.week)} this week, ${gainLabel(w.total.three)} over three weeks`];
  if (queued) parts.push("queued in place of the three weeks' set");
  return parts.filter(Boolean).join(" · ");
}

/** A roster change of the week, no choice in it (#221 part 2): "Thu Oct 23: P7 returns from IL+,
 * sends P3 (+0.20 this week, not in the total)"; a cleared player or a held move's comeback
 * "comes back from IL". */
export function weekBackLine(b: WeekPlanBack, name: (id: number) => string): string {
  const what = `${b.returning ? "returns" : "comes back"} from ${b.slot}`;
  const gain = b.gain ? ` (${gainLabel(b.gain.week)} this week, not in the total)` : "";
  return `${stepDay(b.day)}: ${name(b.player)} ${what}, sends ${name(b.drop)}${gain}`;
}

/** "Thu Oct 23" for a plan step's day. */
export function stepDay(iso: string): string {
  const day = new Date(`${iso}T12:00:00`).toLocaleDateString("en-US", { weekday: "short" });
  return `${day} ${dayLabel(iso)}`;
}

/** What the plan buys against the set: "29 started games against 27 with the set (24 with no
 * move), on 4 adds against 3. It keeps the set's add Brooks for Grant." (#136). */
export function planNote(plan: StreamPlan, name: (id: number | null) => string): string {
  const g = plan.games;
  const n = (k: number) => `${k} ${k === 1 ? "add" : "adds"}`;
  let text =
    `${g.plan} started ${g.plan === 1 ? "game" : "games"} against ${g.set} with the set (${g.none} with no move), ` +
    `on ${n(plan.adds.plan)} against ${plan.adds.set}.`;
  if (plan.base.length) {
    const kept = plan.base.map((x) => `add ${name(x.add)}${x.drop == null && !x.held ? "" : ` for ${forText(x, name)}`}`);
    text += ` It keeps the set's ${kept.join(", ")}.`;
  }
  return text;
}

/** The line under the week's set when the best streaming plan is not recommended (#136), so
 * what was weighed shows: "Streaming Grant's spot buys 2 more started games for +0.04 this week,
 * under the 0.10 floor."; or, when the three-week guard refused the plan with the best week,
 * "... for +0.15 this week but costs 0.47 over three weeks; not recommended."; or, when the
 * season guard did (#164), "... but costs the season −12.4; the season guard holds it back.";
 * null with no plan or a recommended one (its section shows instead). */
export function planShortLine(
  plan: StreamPlan | null | undefined,
  name: (id: number) => string,
  scoring?: string | null,
): string | null {
  if (!plan || plan.recommended) return null;
  const buys = (spots: number[], games: number, gain: number) => {
    const who = spots.length === 1 ? `${name(spots[0])}'s spot` : `the spots of ${andList(spots, name)}`;
    const more = games - plan.games.set;
    const bought = more > 0 ? `${more} more started ${more === 1 ? "game" : "games"} for ` : "";
    return `Streaming ${who} buys ${bought}${gainLabel(gain)} this week`;
  };
  const g = plan.guard;
  if (plan.reason === "guard" && g) {
    return `${buys(g.spots, g.games, g.gain.week)} but costs ${Math.abs(g.gain.three).toFixed(2)} over three weeks; not recommended.`;
  }
  if (plan.reason === "season" && g) {
    return `${buys(g.spots, g.games, g.gain.week)} but costs the season ${rosLabel(g.ros, scoring)}; the season guard holds it back.`;
  }
  const floor = plan.floor.toFixed(2);
  const spots = plan.spots.filter((x) => x.steps > 0).map((x) => x.player);
  if (!spots.length || Number(plan.gain.week.toFixed(2)) <= 0) return `No streaming plan beats the set this week (floor ${floor}).`;
  return `${buys(spots, plan.games.plan, plan.gain.week)}, under the ${floor} floor.`;
}

/** The steps of the plan a guard refused (the three-week guard, or the season guard, #164), by
 * day, to make it by hand (#136): "Thu Oct 22: add Brooks for Grant; Sat Oct 24: add Hale for
 * Brooks"; null for none. */
export function guardSteps(plan: StreamPlan | null | undefined, name: (id: number | null) => string): string | null {
  if (!plan?.guard || (plan.reason !== "guard" && plan.reason !== "season")) return null;
  return plan.guard.steps.map((x) => `${stepDay(x.from)}: add ${name(x.add)} for ${name(x.drop)}`).join("; ");
}

/** "Brooks and Grant" (#124). */
function andList(ids: number[], name: (id: number) => string): string {
  const n = ids.map(name);
  return n.length > 1 ? `${n.slice(0, -1).join(", ")} and ${n[n.length - 1]}` : (n[0] ?? "");
}

/** The players the keep rule keeps, protected first, then those on the bench for a short
 * absence (#124). */
export function keptPlayers(rule: KeepRule | undefined): KeptPlayer[] {
  const rows = rule?.players ?? [];
  return [...rows.filter((k) => k.protected), ...rows.filter((k) => k.bench)];
}

/** The keep rule in a line: who no move drops and why; null when it keeps no one. */
export function keepLine(rule: KeepRule | undefined, name: (id: number) => string): string | null {
  const kept = rule?.players.filter((k) => k.protected && !k.cantcut).map((k) => k.player) ?? [];
  const cut = rule?.players.filter((k) => k.cantcut).map((k) => k.player) ?? [];
  const bench = rule?.players.filter((k) => k.bench) ?? [];
  if (!rule || (!kept.length && !cut.length && !bench.length)) return null;
  const best = rule.best ? `the best add, ${name(rule.best.player)}` : "any add";
  const parts: string[] = [];
  if (kept.length) parts.push(`keeps ${andList(kept, name)} (better than ${best}, over the rest of the season)`);
  if (cut.length) parts.push(`keeps ${andList(cut, name)} (on Yahoo's can't-cut list)`);
  if (bench.length) parts.push(`benches ${bench.map((k) => `${name(k.player)} (back ${dayLabel(k.back)})`).join(", ")}`);
  return `The keep rule ${parts.join(" and ")}: no move drops them.`;
}

/** The keep rule in one phrase (#153), "Keep rule protects 5" and the benched after: the count
 * opens the Strategy card's kept list, and the names, the best add and the reason (keepLine)
 * are its tooltip. Null when it keeps no one. */
export function keepPhrase(rule: KeepRule | undefined): { lead: string; count: number; tail: string } | null {
  const kept = rule?.players.filter((k) => k.protected).length ?? 0;
  const bench = rule?.players.filter((k) => k.bench).length ?? 0;
  if (!kept && !bench) return null;
  if (!kept) return { lead: "Keep rule benches ", count: bench, tail: "" };
  return { lead: "Keep rule protects ", count: kept, tail: bench ? ` and benches ${bench}` : "" };
}

/** The Waivers header in one phrase (#153), "392 players · next 3 weeks", with every other
 * clause it carried in its "?" tooltip, one a line and unchanged. */
export function waiversNote(a: {
  label: string;
  players: number | null | undefined;
  file: string | null | undefined;
  asOf: string | null | undefined;
  horizon: Horizon;
  /** The other system's short name, whose totals show on hover. */
  other: string;
  shown: number;
  total: number;
  /** What the gains mean and the players with no line, once the moves are valued. */
  moves: string | null;
}): { phrase: string; detail: string[] } {
  const read = a.players ? `${a.label}: ${a.players} players` : `${a.label}: nothing read yet`;
  const detail = [read];
  if (a.asOf) detail.push(`${a.file ? `${a.file}, ` : "read "}${a.asOf.slice(0, 10)}`);
  detail.push(`totals over the ${HORIZON_LABEL[a.horizon]}, every game he plays counted`, `hover a total for ${a.other}'s`);
  detail.push(a.shown === a.total ? `the ${a.total} most rostered available players` : `${a.shown} of the ${a.total} most rostered available players`);
  if (a.moves) detail.push(...a.moves.split(" · "));
  const phrase = `${a.players ? `${a.players} players` : "no projection read"} · ${HORIZON_LABEL[a.horizon]}`;
  return { phrase, detail };
}

/** Why the keep rule keeps a player: on Yahoo's can't-cut list (#220), protected, or on the
 * bench until his return. */
export function keptWhy(k: KeptPlayer): string {
  if (k.cantcut) return "can't cut (Yahoo)";
  return k.protected ? "protected" : `bench, back ${dayLabel(k.back)}`;
}

/** The keep rule's tests in words, once for the list: the pool's average, the best add's value
 * and the floor. */
export function keepRuleNote(rule: KeepRule, name: (id: number) => string): string {
  const best = rule.best ? `the best add (${name(rule.best.player)}, ${rule.best.value.toFixed(2)})` : "any add";
  const by = rule.floor ? ` minus ${rule.floor}` : "";
  return (
    `Protected: above the pool's average (${(rule.average ?? 0).toFixed(2)} a game), better than ${best}${by} over the rest of the season, ` +
    `and back this season; benched: better than ${best}${by} and back within a week. No move drops either.`
  );
}

/** "(O, back Nov 2)", "(OFS, no return)": a player's absence. */
function absence(status: string | null, back: string | null): string {
  const when = back ? `back ${dayLabel(back)}` : "no return date";
  return status ? `(${status}, ${when})` : `(${when})`;
}

/** A player who is out, and what to do with him (#124): stash him with the freed spot's best add,
 * who should leave a full slot, bench, or droppable; the value net of return for a protected
 * player. */
export function stashText(a: Stash, name: (id: number | null) => string, scoring?: string | null): string {
  const who = `${name(a.player)} ${absence(a.status, a.back)}`;
  const net = a.protected && a.net != null ? `; ${a.net.toFixed(1)} net of return` : "";
  if (a.advice === "stash") {
    const add = a.add?.three ?? a.add?.week ?? null;
    const span = a.add?.three ? "over the three weeks" : "this week";
    const ros = add?.ros?.value != null ? `, ROS ${rosLabel(add.ros, scoring)}` : "";
    const freed = add ? `, which frees a spot for ${name(add.player)} (${gainLabel(add.gain)} ${span}${ros})` : "";
    return `${who}: move to ${a.slot}${freed}${net}.`;
  }
  if (a.advice === "il_full") {
    const full = `eligible, ${a.slots.join(" or ")} full`;
    const lv = a.leave;
    if (!lv) return `${who}: ${full}${net}.`;
    const leave =
      lv.how === "activate"
        ? lv.drop == null || lv.drop === lv.player
          ? `${name(lv.player)} (cleared) should leave ${lv.slot}, dropped`
          : `activate ${name(lv.player)} (cleared) from ${lv.slot}, dropping ${name(lv.drop)}`
        : `${name(lv.player)} should leave ${lv.slot}, the least value net of return${lv.net != null ? ` (${lv.net.toFixed(1)})` : ""}${lv.protected ? ", though protected: advice only" : ""}`;
    const churn = a.churn ? `; the churn adding ${name(a.churn.add)} below is the better use of the slot` : "";
    return `${who}: ${full}; ${leave}${churn}${net}.`;
  }
  if (a.advice === "bench") return `${who}: bench${a.back ? `, back ${dayLabel(a.back)}` : ""}${net}.`;
  return `${who}: droppable, the moves may take him.`;
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
export function addsNote(a: Pick<MoveAdds, "limit" | "used" | "complete" | "left">): string {
  if (a.limit == null) return "no weekly add limit";
  const used = `${a.complete ? "" : "at least "}${a.used} used this week`;
  return `${a.limit} adds a week · ${used} · ${a.complete ? "" : "at most "}${a.left ?? a.limit} left`;
}

// ---------------------------------------------------------------- rest of the season (#151)
/** What a value in the scorer's units counts: a points league's fantasy points, else the
 * categories' z-sum. */
export function valueUnits(scoring: string | null | undefined): string {
  return scoring === "points" ? "fantasy points" : "the scorer's z-sum, net of an empty line";
}

/** "58", or "57.5" with games extrapolated past the schedule read. */
function gamesCount(g: number): string {
  return Number.isInteger(g) ? String(g) : g.toFixed(1);
}

/** A rest of the season's digits: a season's value runs to hundreds, so a categories league's
 * z-sum to one decimal and a points league's points whole. */
function rosDigits(scoring: string | null | undefined): number {
  return scoring === "points" ? 0 : 1;
}

/** A rest of the season in a cell: "+12.4" (a points league "+310"); blank for none. */
export function rosLabel(r: { value: number | null } | null | undefined, scoring: string | null | undefined): string {
  return gainLabel(r?.value, rosDigits(scoring));
}

/** A season-costly figure reads red; nothing else is coloured, since nothing ranks on it. */
export function rosTone(r: { value: number | null } | null | undefined, scoring: string | null | undefined): "bad" | "" {
  return rosLabel(r, scoring).startsWith("−") ? "bad" : "";
}

/** The ROS column's header hover; ``what`` is whose figure it is. */
export function rosHeadTitle(scoring: string | null | undefined, what = "the move"): string {
  return (
    `ROS: ${what} to the season's end, playoffs included, in ${valueUnits(scoring)}: the add's games less the drop's, ` +
    "each at his per-game value, as the decision log values it. Beside the horizons; nothing ranks on it"
  );
}

/** The games behind a move's figure: "Brooks's 58 games less Grant's 55, Oct 24 to Apr 12, 6 of
 * them past the schedule read at the team's rate". */
export function rosGames(r: MoveRos, x: Pick<MoveRef, "add" | "drop">, name: (id: number) => string): string {
  const add = `${name(x.add)}'s ${gamesCount(r.add_games)} ${r.add_games === 1 ? "game" : "games"}`;
  const drop = x.drop != null && r.drop_games != null ? ` less ${name(x.drop)}'s ${gamesCount(r.drop_games)}` : "";
  const past = r.extrapolated.add + (r.extrapolated.drop ?? 0);
  const extra = past > 0 ? `, ${gamesCount(past)} of them past the schedule read at the team's rate` : "";
  return `${add}${drop}, ${dayLabel(r.from)} to ${dayLabel(r.to)}${extra}`;
}

/** A move's figure on hover: its days and games, its units, and that nothing ranks on it. */
export function rosTitle(
  r: MoveRos | null | undefined,
  x: Pick<MoveRef, "add" | "drop">,
  name: (id: number) => string,
  scoring: string | null | undefined,
): string {
  if (!r) return "not valued to the season's end: no scorer for the league, or no season's end read";
  if (r.value == null) return `not valued to the season's end: ${x.drop == null ? `${name(x.add)} has` : "the add or the drop has"} no line`;
  return `to the season's end, playoffs included: ${rosGames(r, x, name)}; each at his per-game value, in ${valueUnits(scoring)}. The decision log's figure; nothing ranks on it`;
}

/** A plan step's figure on hover: the log's, his add kept to the season's end, and the later
 * step that drops him, which the plan's total nets out. */
export function planStepRosTitle(x: Pick<PlanStep, "add" | "drop" | "ros" | "dropped_by">, name: (id: number) => string, scoring: string | null | undefined): string {
  const text = rosTitle(x.ros, x, name, scoring);
  const by = x.dropped_by;
  return by
    ? `${text}. Valued as kept there: ${stepDay(by.from)}'s step drops ${name(x.add)} for ${name(by.add)}, so the plan's total counts the two together`
    : text;
}

/** "ROS +14.2 against the set's +12.1": the plan's rest of the season beside the set's; null
 * when either is not valued. */
export function planRosText(plan: Pick<StreamPlan, "ros">, scoring: string | null | undefined): string | null {
  const r = plan.ros;
  if (!r?.plan || !r.set) return null;
  return `ROS ${rosLabel(r.plan, scoring)} against the set's ${rosLabel(r.set, scoring)}`;
}

/** A traded player's figure on hover: "58 games from Oct 24 to the season's end, 6 past the
 * schedule read, at +0.21 a game". */
export function playerRosTitle(r: PlayerRos | null | undefined, from: string, scoring: string | null | undefined): string {
  if (!r) return "not valued to the season's end: no line, or no scorer for the league";
  const past = r.extrapolated > 0 ? `, ${gamesCount(r.extrapolated)} past the schedule read` : "";
  return `${gamesCount(r.games)} games from ${dayLabel(from)} to the season's end${past}, at ${unitsLabel(r.per_game, scoring)} a game, in ${valueUnits(scoring)}`;
}

/** A trade side's figure on hover: its roster's before and after from the trade's day, and the
 * players counted as nothing for want of a line. */
export function sideRosTitle(r: TradeSide["ros"], scoring: string | null | undefined): string {
  if (!r) return "not valued to the season's end: no scorer for the league";
  const unvalued = r.unvalued ? `; ${r.unvalued} ${r.unvalued === 1 ? "player without a line counts" : "players without a line count"} nothing` : "";
  return (
    `the roster to the season's end from ${dayLabel(r.from)}, ${r.before.toFixed(rosDigits(scoring))} → ${r.after.toFixed(rosDigits(scoring))} in ${valueUnits(scoring)}: ` +
    `what it receives less what it sends and drops${unvalued}`
  );
}

/** Every player the view names, by Yahoo id: the pool, my roster and the league's rosters. */
export function playersById(s: Pick<SeasonView, "available" | "roster" | "rosters">): Map<number, SeasonPlayer> {
  const out = new Map<number, SeasonPlayer>();
  for (const rows of Object.values(s.rosters)) for (const r of rows) out.set(r.player.yahoo_id, r.player);
  for (const r of s.roster) out.set(r.player.yahoo_id, r.player);
  for (const r of s.available) out.set(r.player.yahoo_id, r.player);
  return out;
}

// ---------------------------------------------------------------- breakout flag (#95)
export const FLAG_SIGNALS: FlagSignalKey[] = ["surge", "minutes", "value", "opportunity"];
export const FLAG_SIGNAL_NAME: Record<FlagSignalKey, string> = {
  surge: "adds surge",
  minutes: "minutes up",
  value: "value gap",
  opportunity: "opportunity",
};
/** The tag's label: the level's name, which the tag's CSS upper-cases (#186). */
export const FLAG_SHORT: Record<FlagLevel, string> = { watch: "watch", add: "add", "must-add": "must-add" };
export const FLAG_TONE: Record<FlagLevel, "tie" | "accent" | "good"> = { watch: "tie", add: "accent", "must-add": "good" };
/** What each level recommends, as the flags legend says it (#185, ruled on the issue). */
export const FLAG_MEANS: Record<FlagLevel, string> = {
  watch: "worth watching; no move is recommended on the flag alone",
  add: "worth an add: open his move (evaluate move) and take it if the Moves card recommends it",
  "must-add": "look first today: open his move; the Moves card says whether the add is recommended, over the player it drops or into an open spot",
};
/** What each signal reads, in words. */
export const FLAG_READS: Record<FlagSignalKey, string> = {
  surge: "Yahoo's buzz index and the players page's % rostered",
  minutes: "the 7- and 14-day past-days exports against the rest-of-season export",
  value: "the rest-of-season export and % rostered",
  opportunity: "ESPN's injury report and the rest-of-season export",
};

/** What the legend says of a player under watch, shown dimmed with the toggle on (#186). */
export const FLAG_UNDER_MEANS = "shown dimmed with “show under watch” on; no move is recommended on the flag alone";
/** Where the "show under watch" toggle is kept, per browser. */
export const WATCH_KEY = "pickandroll.flags.watch";

/** A player's flag, when a signal speaks for him. */
export function flagOf(s: Pick<SeasonView, "flags">, id: number): PlayerFlag | undefined {
  return s.flags?.[String(id)];
}

/** The signals that spoke, loudest first. */
export function flagSignals(f: PlayerFlag): FlagSignalKey[] {
  return FLAG_SIGNALS.filter((k) => (f.signals[k]?.score ?? 0) > 0).sort((a, b) => f.signals[b].score - f.signals[a].score);
}

/** A score as the tag reads it: one decimal, cut rather than rounded, so a 1.46 never reads as a
 * 1.5 floor it has not reached. */
export function flagScore(score: number): string {
  return (Math.floor(score * 10 + 1e-9) / 10).toFixed(1);
}

/** Under watch: no level, but a score that counts (opportunity alone scores 0 and is not). */
export function underWatch(f: PlayerFlag | undefined): f is PlayerFlag {
  return f != null && f.level == null && f.score > 0;
}

/** What a flag's tag reads (#186): its level and score, "add 1.7"; a player under watch reads
 * "under 0.6", and only with ``watch`` on; null for no flag, and for opportunity alone. */
export function flagTag(f: PlayerFlag | undefined, watch = false): { label: string; score: string; level: FlagLevel | null } | null {
  if (f?.level) return { label: FLAG_SHORT[f.level], score: flagScore(f.score), level: f.level };
  return watch && underWatch(f) ? { label: "under", score: flagScore(f.score), level: null } : null;
}

/** The tag's meter (#186): the score's share of the most the four signals add up to, and a tick
 * at each level's floor, lowest first, marked when the score reaches it. */
export function flagMeter(
  score: number,
  cfg?: FlagConfig,
): { fill: number; max: number; ticks: { level: FlagLevel; floor: number; at: number; reached: boolean }[] } {
  const max = cfg?.max ?? FLAG_SIGNALS.length;
  const share = (x: number) => Math.min(1, Math.max(0, x / max));
  const ticks = cfg
    ? [...cfg.levels].sort((a, b) => a.floor - b.floor).map((l) => ({ level: l.level, floor: l.floor, at: share(l.floor), reached: score >= l.floor - 1e-9 }))
    : [];
  return { fill: share(score), max, ticks };
}

/** The "show under watch" toggle as this browser keeps it: on only when stored on, off when the
 * storage cannot be read. */
export function readWatch(store: Pick<Storage, "getItem"> | null): boolean {
  try {
    return store?.getItem(WATCH_KEY) === "1";
  } catch {
    return false;
  }
}

/** Keeps the toggle; when the storage refuses, it lasts the page. */
export function writeWatch(store: Pick<Storage, "setItem"> | null, on: boolean): void {
  try {
    store?.setItem(WATCH_KEY, on ? "1" : "0");
  } catch {
    // Private mode or blocked storage: the toggle lasts the page.
  }
}

/** Opportunity alone: the server scores the flag 0, since it counts only beside another signal. */
function opportunityAlone(f: PlayerFlag): boolean {
  return f.score === 0 && (f.signals.opportunity?.score ?? 0) > 0;
}

/** The flag's levels lowest first, as the API reports them: "watch 0.8, add 1.5, must-add 2.2". */
export function levelsLine(cfg: FlagConfig): string {
  return [...cfg.levels]
    .sort((a, b) => a.floor - b.floor)
    .map((l) => `${l.level} ${l.floor}`)
    .join(", ");
}

/** The hover text: the level and the sum (against the thresholds when the view sent them), then
 * each signal that spoke with its evidence. */
export function flagTitle(f: PlayerFlag, cfg?: FlagConfig): string {
  const head = opportunityAlone(f)
    ? "not flagged: opportunity counts only beside another signal"
    : `${f.level ?? "under watch"} · ${f.score.toFixed(2)}${cfg ? ` of ${cfg.max} (${levelsLine(cfg)})` : ""}`;
  return [head, ...flagSignals(f).map((k) => `${FLAG_SIGNAL_NAME[k]} ${f.signals[k].score.toFixed(2)}: ${f.signals[k].reason ?? ""}`)].join("\n");
}

/** One signal in a player's breakdown (#113). */
export interface BreakdownSignal {
  key: FlagSignalKey;
  name: string;
  score: number;
  /** The evidence with every number; null when the signal said nothing. */
  reason: string | null;
  /** Why today's inputs could not score it for anyone; null when they could. */
  silent: string | null;
  /** False for opportunity alone, which counts only beside another signal. */
  counted: boolean;
}

export interface Breakdown {
  /** All four, in the flag's own order, quiet ones included. */
  signals: BreakdownSignal[];
  sum: number;
  max: number;
  level: FlagLevel | null;
  /** The levels lowest first, each with whether the sum reaches it. */
  levels: { level: FlagLevel; floor: number; reached: boolean }[];
  /** "1.75 of 4: add (from 1.5); must-add at 2.2, 0.45 more". */
  line: string;
}

/** A player's flag as the breakdown under his row shows it: every signal with its score and
 * evidence (a silent one says why), then the sum against the thresholds. */
export function flagBreakdown(f: PlayerFlag, cfg?: FlagConfig, silent?: FlagInputs["silent"]): Breakdown {
  const alone = opportunityAlone(f);
  const signals = FLAG_SIGNALS.map((key): BreakdownSignal => {
    const sig = f.signals[key];
    const score = sig?.score ?? 0;
    return {
      key,
      name: FLAG_SIGNAL_NAME[key],
      score,
      reason: score > 0 ? (sig?.reason ?? null) : null,
      silent: score > 0 ? null : (silent?.[key] ?? null),
      counted: !(alone && key === "opportunity"),
    };
  });
  const levels = cfg ? [...cfg.levels].sort((a, b) => a.floor - b.floor).map((l) => ({ ...l, reached: f.score >= l.floor - 1e-9 })) : [];
  const max = cfg?.max ?? FLAG_SIGNALS.length;
  const sum = `${f.score.toFixed(2)} of ${max}`;
  let line: string;
  if (!levels.length) line = `${sum}: ${f.level ?? "not flagged"}`;
  else if (alone) line = `${sum}: not flagged, opportunity counts only beside another signal; ${levels[0].level} from ${levels[0].floor}`;
  else {
    const at = levels.filter((l) => l.reached).pop();
    const next = levels.find((l) => !l.reached);
    const toNext = next ? `${next.level} at ${next.floor}, ${(next.floor - f.score).toFixed(2)} more` : "";
    line = at ? `${sum}: ${at.level} (from ${at.floor})${toNext ? `; ${toNext}` : ""}` : `${sum}: not flagged; ${toNext}`;
  }
  return { signals, sum: f.score, max, level: f.level, levels, line };
}

/** The "i" text for the breakout flag, every number from the API's config: what each signal
 * reads and how it scores, with the ones today's inputs leave silent named. */
export function flagExplainer(
  cfg: FlagConfig,
  silent?: FlagInputs["silent"],
): { signals: { key: FlagSignalKey; name: string; text: string; silent: string | null }[]; alone: string | null; levels: string; caveat: string } {
  const { surge, minutes, value, opportunity } = cfg.signals;
  const windows = Object.entries(minutes.min_games)
    .sort((a, b) => Number(a[0]) - Number(b[0]))
    .map(([days, games]) => `${games} in ${days} days`)
    .join(", ");
  const text: Record<FlagSignalKey, string> = {
    surge:
      `the day's gain in % rostered against his own level (a gain of ${surge.jump_full}× his level scores 1, a level under ${surge.jump_floor}% counting as ${surge.jump_floor}%), ` +
      `or his Yahoo-wide adds today against his median over at least ${surge.history_days} earlier days (${surge.adds_full}× the median scores 1, a median under ${surge.adds_floor} counting as ${surge.adds_floor}); ` +
      `until those days are kept, his rank by adds on Yahoo's buzz index (the first scores 1, the ${surge.buzz_rows}th ${surge.buzz_last}). The louder part counts.`,
    minutes:
      `minutes a game over the last 7 and 14 days against his rest-of-season projection, the smaller gain of the windows with enough games (${windows}): ` +
      `${minutes.minutes_full} more minutes a game scores 1, and a usage gain of ${minutes.usage_full} points scores the same at weight ${minutes.usage_weight}. ` +
      `It needs a past-days export from the last ${cfg.past_days_max_days} days.`,
    value: `ranked inside the top ${value.rank} on the league's own scoring and rostered in under ${value.pct}% of Yahoo leagues: the better the rank and the lower the %, the higher the score.`,
    opportunity:
      `teammates in his position group (guard, forward, centre) out at least ${opportunity.out_days} more days, by their projected minutes: ${opportunity.full} minutes a game out scores 1, ` +
      `a teammate without a projection counting ${opportunity.unknown_mpg}; nothing while he is out himself.`,
  };
  return {
    signals: FLAG_SIGNALS.map((key) => ({ key, name: cfg.signals[key].name, text: text[key], silent: silent?.[key] ?? null })),
    alone: cfg.opportunity_needs_another ? `Alone, ${cfg.signals.opportunity.name} flags no one: it counts toward the level only beside another signal.` : null,
    levels: `Each signal scores from 0 to 1 and the level comes from their sum, at most ${cfg.max}: ${[...cfg.levels]
      .sort((a, b) => a.floor - b.floor)
      .map((l) => `${l.level} from ${l.floor}`)
      .join(", ")}.`,
    caveat: "Every threshold is a first guess, to be tuned once two weeks of buzz-index history are kept. The flag never adds anyone.",
  };
}

/** The flags legend (#185), every number from the API's config: the levels lowest first with
 * their floors and what each recommends, the signals with their rule and what they read (a silent
 * one says why), the opportunity-only rule, what the flags were read from today, the caveat. */
export function flagLegend(
  cfg: FlagConfig,
  inputs: FlagInputs | undefined,
  now: number,
): {
  levels: { level: FlagLevel; floor: number; means: string }[];
  /** Under watch: below the lowest floor, shown dimmed with the toggle on. */
  under: { below: number; means: string };
  /** The meter's sample: a tag at the second level's floor, its tick reached. */
  sample: { level: FlagLevel; score: number } | null;
  scale: string;
  signals: { key: FlagSignalKey; name: string; rule: string; reads: string; silent: string | null }[];
  alone: string | null;
  read: string;
  caveat: string;
} {
  const x = flagExplainer(cfg, inputs?.silent);
  const levels = [...cfg.levels].sort((a, b) => a.floor - b.floor).map((l) => ({ level: l.level, floor: l.floor, means: FLAG_MEANS[l.level] }));
  return {
    levels,
    under: { below: levels[0]?.floor ?? 0, means: FLAG_UNDER_MEANS },
    sample: levels.length > 1 ? { level: levels[1].level, score: levels[1].floor } : null,
    scale: `Each signal scores from 0 to 1; the level comes from their sum, at most ${cfg.max}.`,
    signals: x.signals.map((sg) => ({ key: sg.key, name: sg.name, rule: sg.text, reads: FLAG_READS[sg.key], silent: sg.silent })),
    alone: x.alone,
    read: flagInputsNote(inputs, now),
    caveat: x.caveat,
  };
}

/** The flagged available players counted by level, for :func:`flagCounts` (the Flags card's
 * note, #185, as the landing grid's). */
export function flagLevels(s: Pick<SeasonView, "flags" | "available">): Record<FlagLevel, number> {
  const n: Record<FlagLevel, number> = { "must-add": 0, add: 0, watch: 0 };
  for (const { flag } of flagged(s)) if (flag.level) n[flag.level] += 1;
  return n;
}

const LEVEL_RANK: Record<FlagLevel, number> = { "must-add": 0, add: 1, watch: 2 };

/** The flagged players (a level, not just a signal), by level, the highest first, and within a
 * level the highest score first, the name breaking ties; with ``watch`` the players under watch
 * follow (#186). */
export function flagged(s: Pick<SeasonView, "flags" | "available">, opts: { watch?: boolean } = {}): { row: AvailableRow; flag: PlayerFlag }[] {
  const rank = (f: PlayerFlag) => (f.level ? LEVEL_RANK[f.level] : 3);
  return s.available
    .map((row) => ({ row, flag: flagOf(s, row.player.yahoo_id) }))
    .filter((x): x is { row: AvailableRow; flag: PlayerFlag } => x.flag?.level != null || (Boolean(opts.watch) && underWatch(x.flag)))
    .sort((a, b) => rank(a.flag) - rank(b.flag) || b.flag.score - a.flag.score || a.row.player.name.localeCompare(b.row.player.name));
}

/** What the flags were read from: "buzz index read 5 min ago · 81 on the injury report · past 7
 * days 2026-10-21 · no past 14 days", with what is missing named. */
export function flagInputsNote(i: FlagInputs | undefined, now: number): string {
  if (!i) return "no flag inputs yet";
  if (i.error) return `no flags: ${i.error}`;
  const parts = [
    i.buzz?.today ? `buzz index read ${ageLabel(i.buzz.today, now)}` : "no buzz index today",
    i.injuries?.read_at ? `${i.injuries.players} on the injury report` : "no injury report",
  ];
  for (const [w, x] of Object.entries(i.past_days ?? {})) {
    parts.push(x ? `past ${w.replace("d", " days")} ${x.as_of.slice(0, 10)}${x.stale ? " (old, not read)" : ""}` : `no past ${w.replace("d", " days")}`);
  }
  if (!i.projection) parts.push("no rest-of-season export");
  return parts.join(" · ");
}

// ---------------------------------------------------------------- trades (#96)
/** A change this small reads as no change. */
const EVEN = 0.005;

/** The trade on our model for one side; never whether the other side will accept it. */
export function tradeVerdict(change: number): string {
  return change >= -EVEN ? "no worse on our model" : "worse on our model";
}

/** The margin in words: how much of its projection what I receive can lose (or must gain)
 * before the trade costs me. */
export function marginText(m: TradeMargin | null): string {
  if (!m) return "";
  if (m.reading === "wins_at_zero") return "no worse for me even if what I receive produces nothing";
  if (m.reading === "loses_at_max") return `worse for me even if what I receive produces ${Math.round(m.max * 100)}% of its projection`;
  return `neutral if what I receive produces ${Math.round((m.neutral ?? 0) * 100)}% of its projection`;
}

/** When the trade takes effect, and on what assumption. */
export function effectiveNote(t: Pick<TradePayload, "effective" | "effective_rule" | "review_days">): string {
  const day = dayLabel(t.effective);
  if (t.effective_rule === "requested") return `takes effect ${day}, the date asked`;
  if (!t.review_days) return `takes effect ${day} if accepted today (the league does not review trades)`;
  return `takes effect ${day} if accepted today, after the league's ${t.review_days}-day review`;
}

/** A side's roster once the trade is processed: whether it fits, what it drops or opens. */
export function rosterNote(r: TradeSide["roster"], name: (id: number) => string): string {
  const held = r.held_moves.map((h) => `${name(h.player)} to ${h.slot}`);
  const parts: string[] = [];
  if (!r.valid) {
    parts.push(
      `not valid in Yahoo as entered: ${r.active} players for ${r.spots} spots, so ${r.drops.map((d) => d.name).join(" and ")} would go (least missed)`,
    );
  } else if (r.open > 0) {
    parts.push(`${r.open} spot${r.open > 1 ? "s" : ""} open`);
  } else {
    parts.push("fits");
  }
  if (held.length) parts.push(held.join(", "));
  return parts.join("; ");
}

/** "1 + 2": a traded player's games on his old team (until the date) and his new one. */
export function movedGames(p: TradePlayer, h: "week" | "three"): string {
  const g = p.games[h];
  return `${g.old.games} + ${g.new.games}`;
}

/** The hover for a traded player's games: starts as well, and the games as things stand. */
export function movedGamesTitle(p: TradePlayer, h: "week" | "three", oldName: string, newName: string): string {
  const g = p.games[h];
  return `${g.old.games} games (${g.old.started} started) for ${oldName}, then ${g.new.games} (${g.new.started} started) for ${newName}; ${g.before.games} games without the trade`;
}

/** "5-3-1 W" (categories won, lost, tied) or "810.5–790.3 W" (points): a recorded week's result. */
export function weekResult(r: WeekResult | null | undefined): string {
  if (!r) return "";
  if (r.points != null) return `${round1(r.points)}–${round1(r.against ?? 0)} ${r.outcome}`;
  return `${r.won ?? 0}-${r.lost ?? 0}-${r.tied ?? 0} ${r.outcome}`;
}

function round1(x: number): string {
  return String(Math.round(x * 10) / 10);
}

/** A won week reads good, a lost one bad, a tie neither. */
export function weekTone(r: WeekResult | null | undefined): "good" | "bad" | "" {
  return r?.outcome === "W" ? "good" : r?.outcome === "L" ? "bad" : "";
}

// ---------------------------------------------------------------- landing grid (#108)
/** "5-3", "93.2–101.9": my week's score so far, mine first (categories won, or points). */
export function scoreLabel(s: Pick<SeasonSummary, "score" | "scoring">): string {
  if (!s.score) return "no score yet";
  const [mine, theirs] = s.score;
  return s.scoring === "points" ? `${round1(mine)}–${round1(theirs)}` : `${mine}-${theirs}`;
}

/** "4th of 12", my place in the standings. */
export function placeLabel(s: Pick<SeasonSummary, "my_team" | "num_teams">): string {
  const rank = s.my_team?.rank;
  return rank != null ? `${ordinal(rank)} of ${s.num_teams}` : "no place yet";
}

/** "3 of 4 adds left" ("at most" when the transactions page may not reach the week's start). */
export function addsLeft(a: SeasonSummary["adds"]): string {
  if (!a) return "";
  if (a.limit == null) return "no add limit";
  return `${a.complete ? "" : "at most "}${a.left ?? a.limit} of ${a.limit} adds left`;
}

/** "1 add · 11 watch": the pool's flagged players by level, the highest first. */
export function flagCounts(flags: SeasonSummary["flags"]): string {
  if (!flags) return "";
  const parts = (["must-add", "add", "watch"] as const).filter((k) => flags[k]).map((k) => `${flags[k]} ${k}`);
  return parts.join(" · ") || "no flags";
}

/** A card's gain for the grid's order: its best move's, null when not solved or none gains. */
export function bestGain(b: BestMove | undefined): number | null {
  return b?.status === "solved" && b.move ? b.move.gain : null;
}

/** "Add Name for Name", or "Add Name" for an open spot. */
export function bestLine(b: Extract<BestMove, { status: "solved" }>): string {
  const m = b.move;
  if (!m) return `no move gains ${b.min_gain}`;
  const add = m.add_name ?? `player ${m.add}`;
  return m.drop == null ? `Add ${add}` : `Add ${add} for ${m.drop_name ?? `player ${m.drop}`}`;
}

export type GridOrder = "gain" | "name";

/** The in-season grid's cards: by most to gain (the leagues not solved yet next, then those
 * where no move gains, the leagues not read last), or by name; by name within each. */
export function gridOrder(seasons: SeasonSummary[], best: Map<string, BestMove | undefined>, by: GridOrder): SeasonSummary[] {
  const title = (s: SeasonSummary) => s.name ?? s.league;
  const read = (s: SeasonSummary) => !s.error && s.has_snapshot;
  const group = (s: SeasonSummary) => {
    if (!read(s)) return 3;
    const b = best.get(s.league);
    return b?.status !== "solved" ? 1 : b.move ? 0 : 2;
  };
  const gain = (s: SeasonSummary) => bestGain(best.get(s.league)) ?? 0;
  return [...seasons].sort((a, b) =>
    by === "name"
      ? Number(read(b)) - Number(read(a)) || title(a).localeCompare(title(b))
      : group(a) - group(b) || gain(b) - gain(a) || title(a).localeCompare(title(b)),
  );
}

// ---------------------------------------------------------------- landing table (#191)
/** The landing table's leagues: the private league pinned first whatever the sort, then the rest
 * in the grid's order; the points leagues held back unless shown, with how many were. A private
 * points league is pinned, never hidden. */
export interface LandingRows {
  pinned: SeasonSummary[];
  rest: SeasonSummary[];
  hidden: number;
}

/** Whether the landing table shows a league: the private one always, a points league only when
 * the points leagues are shown. */
export function onLanding(s: Pick<SeasonSummary, "public" | "scoring">, showPoints: boolean): boolean {
  return s.public === false || showPoints || s.scoring !== "points";
}

export function landingRows(
  seasons: SeasonSummary[],
  best: Map<string, BestMove | undefined>,
  by: GridOrder,
  showPoints: boolean,
): LandingRows {
  const others = seasons.filter((s) => s.public !== false);
  const shown = others.filter((s) => onLanding(s, showPoints));
  const pinned = seasons.filter((s) => s.public === false);
  return { pinned: gridOrder(pinned, best, by), rest: gridOrder(shown, best, by), hidden: others.length - shown.length };
}

/** The table's head: "9 categories leagues", or with the points leagues shown "12 leagues: 9
 * categories, 3 points". */
export function leaguesLabel(shown: Pick<SeasonSummary, "scoring">[]): string {
  const points = shown.filter((s) => s.scoring === "points").length;
  const cats = shown.length - points;
  const of = (n: number, kind: string) => `${n} ${kind} league${n === 1 ? "" : "s"}`;
  if (!points) return of(cats, "categories");
  if (!cats) return of(points, "points");
  return `${shown.length} leagues: ${cats} categories, ${points} points`;
}

/** The recommended set in a line: "3 moves recommended together add +0.60 over weeks 2-4 against
 * the field"; "not solved yet" before today's solve; blank while the look runs. */
export function setSummary(b: BestMove | undefined): string {
  if (!b) return "";
  if (b.status !== "solved") return "not solved yet";
  if (!b.moves) return `no move gains ${b.min_gain} over ${b.label}`;
  return b.moves === 1
    ? `1 move recommended adds ${gainLabel(b.gain)} over ${b.label}`
    : `${b.moves} moves recommended together add ${gainLabel(b.gain)} over ${b.label}`;
}

/** A player the best route names, by id; "player 7" for one it does not. */
export function bestNamer(b: Extract<BestMove, { status: "solved" }>): (id: number) => string {
  return (id) => b.names?.[String(id)] ?? `player ${id}`;
}

/** A set's move as the panel lists it: "Add X for Y", "Add X after Z to IL", "Add X (free: open
 * spot)" (#187's words), and the kind for its last column: "drop", "IL move" or "open spot". */
export function setLine(m: BestSetLine, name: (id: number) => string): { text: string; kind: string; basis: Basis } {
  const basis = addBasis(m, name);
  const kind =
    basis.kind === "drop" ? "drop" : basis.kind === "churn" ? "churn" : basis.kind === "held" && m.held ? `${m.held.slot} move` : "open spot";
  return { text: `Add ${name(m.add)} ${basisPhrase(basis)}`, kind, basis };
}

/** My place's tone: good in the top two, bad when last. */
export function placeTone(s: Pick<SeasonSummary, "my_team" | "num_teams">): "good" | "bad" | "" {
  const rank = s.my_team?.rank;
  if (rank == null) return "";
  return rank <= 2 ? "good" : rank === s.num_teams ? "bad" : "";
}

/** Whether a league's panel is open: the user's toggle, else open for the private league only. */
export function isExpanded(s: Pick<SeasonSummary, "league" | "public">, toggled: ReadonlyMap<string, boolean>): boolean {
  return toggled.get(s.league) ?? s.public === false;
}

/** The toggles after the chevron of ``s`` is clicked. */
export function toggleExpanded(s: Pick<SeasonSummary, "league" | "public">, toggled: ReadonlyMap<string, boolean>): Map<string, boolean> {
  return new Map(toggled).set(s.league, !isExpanded(s, toggled));
}

// ---------------------------------------------------------------- strategy (#110)
/** A run still going: the panel polls it. */
export function isSolving(p: Pick<StrategyPayload, "status"> | undefined): boolean {
  return p?.status === "solving";
}

/** What a gain counts this week and over the rest of the season: categories and category-weeks,
 * or in a points league matchups on both. */
export function strategyUnits(scoring: SeasonView["scoring"]): { week: string; season: string } {
  return scoring === "points" ? { week: "matchups", season: "matchups" } : { week: "categories", season: "category-weeks" };
}

/** The point the panel opens on: the recommended weight's (#152), else the natural weight's, else
 * the first. */
export function defaultWeight(points: Pick<StrategyPoint, "key" | "natural" | "recommended">[] | undefined): StrategyWeightKey | null {
  if (!points?.length) return null;
  return (points.find((p) => p.recommended) ?? points.find((p) => p.natural) ?? points[0]).key;
}

/** The linear program's status as the panel says it: solved, time-limited, no set, running. */
export function milpLabel(m: MilpBlock | null | undefined, limit: number): string {
  if (!m || m.status === "pending") return "running";
  if (m.status === "optimal") return "solved";
  if (m.status === "time_limited") return `time-limited at ${limit} s`;
  return "no set";
}

/** Where a point's recommended set came from, in words: the search's first, then whichever of
 * the two is better on the weight's own value once the program is in. */
export function sourceText(p: Pick<StrategyPoint, "stage" | "source" | "note" | "ahead" | "milp" | "season_guard">, limit: number): string {
  const status = milpLabel(p.milp, limit);
  if (p.stage !== "done" || !p.source) return "Recommended by the exact search; the linear program is still running.";
  if (p.source === "both") return `Recommended by both: the exact search and the linear program (${status}) found the same set.`;
  const by = p.ahead != null && p.ahead > 0.005 ? gainLabel(p.ahead) : null;
  if (p.source === "milp") return `Recommended by the linear program (${status})${by ? `, ahead of the search's set by ${by}` : ""}.`;
  if (p.milp?.status === "failed") return "Recommended by the exact search; the linear program found no set.";
  if (p.season_guard?.held_back && p.season_guard.program) {
    return `Recommended by the exact search: the season guard held back the linear program's set (${status}), which costs the season.`;
  }
  const from = p.note ? `, from ${p.note}` : "";
  return by
    ? `Recommended by the exact search${from}, ahead of the linear program's set (${status}) by ${by}.`
    : `Recommended by the exact search${from}; the linear program (${status}) found nothing better.`;
}

/** A mark on the frontier: the weights whose sets land on the same gains share one. */
export interface FrontierMark {
  x: number;
  y: number;
  keys: StrategyWeightKey[];
  /** The first weight's source; pending while the program runs. */
  source: StrategySource | "pending";
  natural: boolean;
}

/** The frontier's marks: this week's gain across, the rest of the season's up, in the weights'
 * order. */
export function frontierMarks(points: StrategyPoint[]): FrontierMark[] {
  const out: FrontierMark[] = [];
  for (const p of points) {
    if (!p.gain) continue;
    const at = out.find((m) => Math.abs(m.x - p.gain!.week) < 0.0005 && Math.abs(m.y - p.gain!.season) < 0.0005);
    if (at) {
      at.keys.push(p.key);
      at.natural ||= p.natural;
      continue;
    }
    out.push({ x: p.gain.week, y: p.gain.season, keys: [p.key], source: p.stage === "done" && p.source ? p.source : "pending", natural: p.natural });
  }
  return out;
}

/** An axis's range: zero (no move) always in, padded so no mark sits on an edge. */
export function axisRange(values: number[]): [number, number] {
  const lo = Math.min(0, ...values);
  const hi = Math.max(0, ...values);
  const pad = Math.max(0.05, (hi - lo) * 0.12);
  return [lo - (lo < 0 ? pad : pad / 2), hi + pad];
}

/** Round tick values for an axis, three to six whatever the spread. */
export function axisTicks(lo: number, hi: number): number[] {
  const span = hi - lo;
  const raw = span / 4;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((f) => f * mag).find((x) => span / x <= 6) ?? 10 * mag;
  const out: number[] = [];
  for (let i = Math.ceil(lo / step - 1e-9); i * step <= hi + 1e-9; i++) out.push(Number((i * step).toFixed(6)));
  return out;
}

/** The first-order values as two lists: the pool's highest not in the set (whom to look at
 * next) and my lowest not already dropped (whom a move would send), each with its value. */
export function firstOrderLists(
  fo: Record<string, number> | undefined,
  pool: number[],
  roster: number[],
  set: Pick<MoveRef, "add" | "drop">[],
  n = 5,
): { adds: [number, number][]; mine: [number, number][] } {
  if (!fo) return { adds: [], mine: [] };
  const added = new Set(set.map((m) => m.add));
  const dropped = new Set(set.map((m) => m.drop));
  const of = (ids: number[]) => ids.filter((id) => fo[String(id)] != null).map((id): [number, number] => [id, fo[String(id)]]);
  const adds = of(pool.filter((id) => !added.has(id))).sort((a, b) => b[1] - a[1] || a[0] - b[0]);
  const mine = of(roster.filter((id) => !dropped.has(id))).sort((a, b) => a[1] - b[1] || a[0] - b[0]);
  return { adds: adds.slice(0, n), mine: mine.slice(0, n) };
}

/** The panel's locks and switch differ from the shown run's: a solve would give another answer. */
export function strategySettingsChanged(run: StrategySettings | undefined, lock: number[], programOnly: boolean): boolean {
  if (!run) return false;
  const a = [...run.keep].sort((x, y) => x - y);
  const b = [...new Set(lock)].sort((x, y) => x - y);
  return run.program_only !== programOnly || a.length !== b.length || a.some((x, i) => x !== b[i]);
}

// ---------------------------------------------------------------- the scorecard (#126)
export const MATCH_WORDS: Record<MatchKind, string> = {
  as_recommended: "as recommended",
  differently: "differently",
  not_recommended: "not recommended",
  no_entry: "no solve before it",
};

export const UNSCORED_WORDS: Record<UnscoredReason, string> = {
  no_time: "no time on the transactions page",
  no_scorer: "no scorer logged",
  not_read: "no box score read yet",
  unmatched: "a player not matched to the box scores",
};

/** A value in the scorer's units: a points league's fantasy points to one decimal, a categories
 * league's z-sum to two; blank for none. */
export function unitsLabel(v: number | null | undefined, scoring: string | null | undefined): string {
  return gainLabel(v, scoring === "points" ? 1 : 2);
}

/** A recorded week in a line: "projected 70% to win, 4.3 categories · W 5-3-1 · 2nd of 12, 9-7-2". */
export function scorecardWeekLine(w: ScorecardWeek): string {
  const points = w.scoring === "points";
  const p = w.projected;
  const parts = [
    p?.matchup != null
      ? `projected ${Math.round(p.matchup * 100)}% to win${!points && p.expected != null ? `, ${p.expected.toFixed(1)} categories` : ""}`
      : "not projected",
  ];
  const r = w.actual?.result;
  if (r) parts.push(points ? `${r.outcome} ${(r.points ?? 0).toFixed(1)}-${(r.against ?? 0).toFixed(1)}` : `${r.outcome} ${r.won}-${r.lost}-${r.tied}`);
  else parts.push("no result");
  const st = w.standing;
  if (st?.rank) parts.push(`${ordinal(st.rank)} of ${st.teams}${st.record ? `, ${st.record}` : ""}`);
  return parts.join(" · ");
}

/** The season so far in a line: the record, and over the projected weeks the wins and
 * categories against those expected and the matchup odds' Brier score. */
export function scorecardToDateLine(td: ScorecardToDate, brier?: number | null): string {
  const parts = [td.record];
  if (td.projected && td.expected_wins != null) {
    parts.push(`${td.wins} win${td.wins === 1 ? "" : "s"} against ${td.expected_wins.toFixed(2)} expected over ${td.projected} projected week${td.projected === 1 ? "" : "s"}`);
    if (td.categories != null && td.expected_categories != null) parts.push(`${td.categories} categories against ${td.expected_categories.toFixed(1)}`);
    if (brier != null) parts.push(`Brier ${brier.toFixed(3)}`);
  }
  return parts.join(" · ");
}

/** My moves of some weeks in a line: the groups, their realized value on their weeks and the
 * scored against their projection, each on the horizon its set was recommended for (#143). */
export function movesSummaryLine(m: MovesSummary, scoring: string | null | undefined): string {
  if (!m.made) return "no moves";
  const parts = [`${m.made} move${m.made === 1 ? "" : "s"}: ${m.scored} scored, ${m.realized_only} realized only, ${m.unscored} unscored`];
  if (m.scored + m.realized_only) parts.push(`${unitsLabel(m.realized_value.week ?? 0, scoring)} realized on their weeks`);
  const c = m.compared;
  if (c) {
    const share = c.share != null ? ` (${Math.round(c.share * 100)}%)` : "";
    parts.push(`scored ${unitsLabel(c.realized, scoring)} against ${unitsLabel(c.projected, scoring)} projected${share} on their horizons, ${c.same_way} of ${c.moves} the projected way`);
  }
  return parts.join(" · ");
}

/** "Add Brooks for Grant", "Add Brooks", "Drop Grant". */
export function moveWhat(m: Pick<ScorecardMove, "add" | "drop">, name: (id: number) => string): string {
  if (m.add != null) return `Add ${name(m.add)}${m.drop != null ? ` for ${name(m.drop)}` : ""}`;
  return m.drop != null ? `Drop ${name(m.drop)}` : "";
}

/** A move's realized value on a horizon, or what stands in for it: "−" with no value. */
export function realizedLabel(m: ScorecardMove, h: MoveHorizon, scoring: string | null | undefined): string {
  const v = m.realized?.valued ? m.realized.horizons[h]?.value : null;
  return v == null ? "−" : unitsLabel(v, scoring);
}

/** A move's realized value spelled out for its row's tooltip: each span's games and values and
 * how far it is read, the borrowed scorer, the lag behind the solve, or why it has no value. */
export function realizedTitle(m: ScorecardMove, scoring: string | null | undefined): string {
  const x = m.realized;
  if (!x) return "not valued: no box scores";
  const n = (k: number, word: string) => `${k} ${word}${k === 1 ? "" : "s"}`;
  const parts: string[] = [];
  if (!x.valued && x.reason) parts.push(`no realized value: ${UNSCORED_WORDS[x.reason]}`);
  for (const [h, label] of [
    ["week", "its week"],
    ["three", "the three weeks after"],
  ] as const) {
    const span = x.horizons[h];
    if (!span) continue;
    const games = [span.add_games != null && m.add != null ? `${n(span.add_games, "game")} added` : null, span.drop_games != null && m.drop != null ? `${span.drop_games} given up` : null].filter(Boolean);
    const read = span.complete ? "" : span.through ? `, read through ${dayLabel(span.through)}` : ", none read yet";
    const value = span.value != null ? `: ${unitsLabel(span.value, scoring)}` : "";
    const gaps = span.gaps ? `, ${n(span.gaps, "game")} of a player not matched` : "";
    const missing = span.missing.length ? `, ${n(span.missing.length, "day")} over not read` : "";
    parts.push(`${label} (${dayLabel(span.from)} – ${dayLabel(span.to)}${read})${games.length ? `, ${games.join(", ")}` : ""}${gaps}${missing}${value}`);
  }
  if (x.scorer && !x.scorer.own) parts.push("valued with the nearest solve's scorer: realized only");
  if (x.lag_days) parts.push(`made ${n(x.lag_days, "day")} after the first day of the solve it matched`);
  return parts.join("; ");
}
