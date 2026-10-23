// The Progress screen's arithmetic (#129): the payload's league weeks cut to a scope (the public
// leagues pooled, or one league) and a week range, the running sums over that range, the headline
// figures, and the knob changes in words. Pure, so its tests run under node.
import type { CalibrationBucket, KnobChange, KnobName, MatchKind, MoveHorizon, MovesCompared, PooledWeek, ProgressLeague, ProgressMove, ProgressPayload, ProgressSentence, ProgressWeek, Scoring } from "./api";

/** The scope of the public leagues pooled; any other scope is a league's id. */
export const POOLED = "pooled";

export type Metric = "wins" | "categories" | "standing";

export const METRICS: { id: Metric; label: string; title: string }[] = [
  { id: "wins", label: "Wins", title: "matchups won, a tie as half, against the odds of winning each, summed over the weeks" },
  { id: "categories", label: "Categories", title: "categories won against those expected, summed over the weeks (categories leagues only)" },
  { id: "standing", label: "Standing", title: "the place in the league after each week; pooled, the mean place of the public leagues" },
];

/** The knobs by a short name for the tables, and in full for the sheet. */
export const KNOB_SHORT: Record<KnobName, string> = {
  system: "system",
  blend: "blend",
  horizon_weight: "horizon",
  protection_floor: "floor",
  plan_floor_cats: "plan floor (cats)",
  plan_floor_points: "plan floor (points)",
  stash_threshold: "stash",
  faab_sizing: "FAAB",
  daily_cap: "cap",
};
export const KNOB_TITLE: Record<KnobName, string> = {
  system: "projection system",
  blend: "blend",
  horizon_weight: "horizon weight",
  protection_floor: "protection floor",
  plan_floor_cats: "plan floor, categories",
  plan_floor_points: "plan floor, points",
  stash_threshold: "stash threshold",
  faab_sizing: "FAAB sizing",
  daily_cap: "daily move cap",
};

/** docs/AUTOPILOT.md section 6: how a change is judged. The view never decides a verdict. */
export const CHANGE_RULE = "A change is judged on the two weeks from its Monday and on the season to date, and reverted when worse.";
/** A change is judged on this many weeks (season/progress.py JUDGED_WEEKS). */
export const JUDGED_WEEKS = 2;

/** The units of a league's moves, by its scoring: never summed across the two. */
export const UNITS: Record<Scoring, string> = { points: "fantasy points", categories: "category value" };
export const UNITS_SHORT: Record<Scoring, string> = { points: "pts", categories: "value" };

export const LINEUP_LOST_TITLE = "not recorded yet: counted once the lineup log exists";

/** The scored moves with a complete week, summed: realized against projected. */
export interface MovesSum {
  moves: number;
  projected: number;
  realized: number;
  same_way: number;
  /** Realized over projected; null when the projected is not positive. */
  share: number | null;
}

/** A league's line in a week, for the chart's tip and the week strip. */
export interface LeagueLine {
  league: string;
  outcome: ProgressWeek["outcome"];
  expected: number | null;
  won: number | null;
  rank: number | null;
}

/** A week of a scope, its own figures: one league's, or the public leagues' summed (the mean
 * for the place and the Brier score). */
export interface ScopeWeek {
  week: number;
  start: string;
  end: string;
  /** The matchups with odds and a result. */
  projected: number;
  expected: number;
  won: number;
  /** W, L and T over every result. */
  record: [number, number, number];
  /** Over the categories leagues with both. */
  expectedCategories: number | null;
  categories: number | null;
  rank: number | null;
  teams: number | null;
  brier: number | null;
  made: number;
  /** The week's realized value of every valued move, by scoring. */
  realized: Partial<Record<Scoring, number>>;
  compared: Partial<Record<Scoring, MovesSum>>;
  lines: LeagueLine[];
}

const round = (x: number, digits = 4) => Number(x.toFixed(digits));
const mean = (xs: number[]) => (xs.length ? round(xs.reduce((a, b) => a + b, 0) / xs.length) : null);

export function addMoves(a: MovesSum | undefined, c: MovesCompared | MovesSum): MovesSum {
  const moves = (a?.moves ?? 0) + c.moves;
  const projected = round((a?.projected ?? 0) + c.projected);
  const realized = round((a?.realized ?? 0) + c.realized);
  return { moves, projected, realized, same_way: (a?.same_way ?? 0) + c.same_way, share: projected > 0 ? round(realized / projected) : null };
}

/** The leagues a scope covers: every public league recorded for the pooled scope, else the one. */
export function scopeLeagues(p: ProgressPayload, scope: string): ProgressLeague[] {
  return p.leagues.filter((l) => l.weeks.length > 0 && (scope === POOLED ? l.public : l.league === scope));
}

/** The scope's weeks, from ``from`` to ``to``, each as the leagues' rows sum it. */
export function scopeWeeks(p: ProgressPayload, scope: string, from = 1, to = Infinity): ScopeWeek[] {
  const leagues = scopeLeagues(p, scope);
  const out: ScopeWeek[] = [];
  for (const w of p.weeks) {
    if (w.week < from || w.week > to) continue;
    const rows = leagues.flatMap((l) => l.weeks.filter((r) => r.week === w.week).map((r) => ({ league: l.league, r })));
    if (!rows.length) continue;
    const projected = rows.filter(({ r }) => r.expected != null && r.won != null);
    const cats = rows.filter(({ r }) => r.expected_categories != null && r.categories != null);
    const ranks = rows.filter(({ r }) => r.rank != null);
    const realized: Partial<Record<Scoring, number>> = {};
    const compared: Partial<Record<Scoring, MovesSum>> = {};
    for (const { r } of rows) {
      const s = r.scoring ?? "categories";
      if (r.moves.realized != null) realized[s] = round((realized[s] ?? 0) + r.moves.realized);
      if (r.moves.compared) compared[s] = addMoves(compared[s], r.moves.compared);
    }
    const count = (x: string) => rows.filter(({ r }) => r.outcome === x).length;
    out.push({
      week: w.week,
      start: w.start,
      end: w.end,
      projected: projected.length,
      expected: round(projected.reduce((a, { r }) => a + r.expected!, 0)),
      won: round(projected.reduce((a, { r }) => a + r.won!, 0)),
      record: [count("W"), count("L"), count("T")],
      expectedCategories: cats.length ? round(cats.reduce((a, { r }) => a + r.expected_categories!, 0)) : null,
      categories: cats.length ? round(cats.reduce((a, { r }) => a + r.categories!, 0)) : null,
      rank: mean(ranks.map(({ r }) => r.rank!)),
      teams: rows.length === 1 ? rows[0].r.teams : null,
      brier: mean(projected.map(({ r }) => r.brier).filter((b): b is number => b != null)),
      made: rows.reduce((a, { r }) => a + r.moves.made, 0),
      realized,
      compared,
      lines: rows.map(({ league, r }) => ({ league, outcome: r.outcome, expected: r.expected, won: r.won, rank: r.rank })),
    });
  }
  return out;
}

/** A point of the Trend chart: the actual and the expected summed to the week over the range
 * (the place after it for the standing, which has no expected line). */
export interface TrendPoint {
  week: number;
  actual: number | null;
  expected: number | null;
  w: ScopeWeek;
}

export function trend(weeks: ScopeWeek[], metric: Metric): TrendPoint[] {
  let actual = 0;
  let expected = 0;
  let seen = false;
  return weeks.map((w) => {
    if (metric === "standing") return { week: w.week, actual: w.rank, expected: null, w };
    if (metric === "wins") {
      actual += w.won;
      expected += w.expected;
      seen ||= w.projected > 0;
    } else if (w.categories != null && w.expectedCategories != null) {
      actual += w.categories;
      expected += w.expectedCategories;
      seen = true;
    }
    return { week: w.week, actual: seen ? round(actual) : null, expected: seen ? round(expected) : null, w };
  });
}

/** The range's figures for the headline tiles: the record, wins and categories against
 * expected, the place first and last, the scored moves by scoring, and the Brier score. */
export interface RangeSum {
  weeks: number;
  record: [number, number, number];
  projected: number;
  expected: number;
  won: number;
  expectedCategories: number | null;
  categories: number | null;
  rankFirst: number | null;
  rankLast: number | null;
  made: number;
  realized: Partial<Record<Scoring, number>>;
  compared: Partial<Record<Scoring, MovesSum>>;
  brierLast: number | null;
  brier: number | null;
}

export function rangeSum(weeks: ScopeWeek[]): RangeSum {
  const out: RangeSum = {
    weeks: weeks.length,
    record: [0, 0, 0],
    projected: 0,
    expected: 0,
    won: 0,
    expectedCategories: null,
    categories: null,
    rankFirst: null,
    rankLast: null,
    made: 0,
    realized: {},
    compared: {},
    brierLast: null,
    brier: null,
  };
  // The Brier score over the range is the mean over its matchups, not over its weeks.
  let brierSum = 0;
  let brierN = 0;
  for (const w of weeks) {
    w.record.forEach((n, i) => (out.record[i] += n));
    out.projected += w.projected;
    out.expected = round(out.expected + w.expected);
    out.won = round(out.won + w.won);
    if (w.categories != null && w.expectedCategories != null) {
      out.categories = round((out.categories ?? 0) + w.categories);
      out.expectedCategories = round((out.expectedCategories ?? 0) + w.expectedCategories);
    }
    if (w.rank != null) {
      out.rankFirst ??= w.rank;
      out.rankLast = w.rank;
    }
    out.made += w.made;
    for (const [s, v] of Object.entries(w.realized) as [Scoring, number][]) out.realized[s] = round((out.realized[s] ?? 0) + v);
    for (const [s, c] of Object.entries(w.compared) as [Scoring, MovesSum][]) out.compared[s] = addMoves(out.compared[s], c);
    if (w.brier != null) {
      out.brierLast = w.brier;
      brierSum += w.brier * w.projected;
      brierN += w.projected;
    }
  }
  out.brier = brierN ? round(brierSum / brierN) : null;
  return out;
}

/** "6-4", or "6-4-1" with a tie. */
export function recordLabel([w, l, t]: [number, number, number]): string {
  return t ? `${w}-${l}-${t}` : `${w}-${l}`;
}

/** The weeks recorded for a scope, first and last; null with none. */
export function recordedRange(p: ProgressPayload, scope: string): [number, number] | null {
  const weeks = scopeLeagues(p, scope).flatMap((l) => l.weeks.map((r) => r.week));
  return weeks.length ? [Math.min(...weeks), Math.max(...weeks)] : null;
}

/** A range stepped: its first week or its last by ``delta``, within ``bounds`` and never past the other end. */
export function stepRange(range: [number, number], bounds: [number, number], end: 0 | 1, delta: number): [number, number] {
  const next: [number, number] = [...range];
  next[end] = Math.max(bounds[0], Math.min(bounds[1], range[end] + delta));
  if (next[0] > next[1]) return range;
  return next;
}

/** The sentences a scope shows: the pooled ones with the leagues named in them, or the league's own. */
export function scopeSentences(sentences: ProgressSentence[], scope: string): ProgressSentence[] {
  return sentences.filter((s) => (scope === POOLED ? s.scope === POOLED || s.topic === "league" : s.scope === scope));
}

/** A knob's value as the files hold it: a number, a word, or nothing. */
export function knobValue(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number" || typeof v === "string" || typeof v === "boolean") return String(v);
  return JSON.stringify(v);
}

/** "blend 0.5 → 0.6" */
export function changeWhat(c: KnobChange, names: Record<KnobName, string> = KNOB_SHORT): string {
  return `${names[c.knob] ?? c.knob} ${knobValue(c.from)} → ${knobValue(c.to)}`;
}

/** The week after which a change is judged; null before its week is known. */
export function judgedAfter(c: KnobChange): number | null {
  return c.week == null ? null : c.week + JUDGED_WEEKS - 1;
}

/** A change's verdict in a few words: kept or reverted with A's wins above expected over B's,
 * or when it is judged. */
export function verdictLabel(c: KnobChange): { text: string; tone: "good" | "bad" | "dim"; figure: string | null } {
  if (!c.verdict) {
    const after = judgedAfter(c);
    return { text: after == null ? "pending" : `judged after wk ${after}`, tone: "dim", figure: null };
  }
  return { text: c.verdict, tone: c.verdict === "kept" ? "good" : "bad", figure: abGap(c) };
}

/** A's wins above expected a league over B's, over the weeks the change is judged on. */
export function abGap(c: KnobChange): string | null {
  const a = c.ab?.a.wins_above;
  const b = c.ab?.b.wins_above;
  if (a == null || b == null) return null;
  const g = round(a - b, 1);
  return `${g > 0 ? "+" : g < 0 ? "−" : ""}${Math.abs(g).toFixed(1)} A over B`;
}

/** The changes stepped from ``id`` by ``delta``, oldest first, wrapping round. */
export function stepChange(changes: KnobChange[], id: string, delta: number): string {
  const i = changes.findIndex((c) => c.id === id);
  if (i < 0 || !changes.length) return id;
  return changes[(i + delta + changes.length) % changes.length].id;
}

/** The note a change's sheet quotes for why it was tried: the Decision of the note posted on its Monday. */
export function whyTried(p: ProgressPayload, c: KnobChange): { text: string; from: string } | null {
  const n = p.notes.find((x) => x.monday === c.monday);
  if (n?.decision) return { text: n.decision, from: `the ${n.monday} note` };
  if (c.reason) return { text: c.reason, from: "the knob file" };
  return null;
}

/** The public leagues recorded, for a change's B half count. */
export function publicLeagues(p: ProgressPayload): string[] {
  return p.leagues.filter((l) => l.public && l.weeks.length > 0).map((l) => l.league);
}

// ---------------------------------------------------------------- the moves (PR 3)
export type MatchFilter = "all" | MatchKind;

/** A match in a table cell, and its tag's tone. */
export const MATCH_SHORT: Record<MatchKind, string> = { as_recommended: "as reco", differently: "differently", not_recommended: "not reco", no_entry: "no solve" };
export const MATCH_TONE: Record<MatchKind, "good" | "accent" | "bad" | "tie"> = { as_recommended: "good", differently: "accent", not_recommended: "bad", no_entry: "tie" };
/** What each match means, from the decision log (#125). */
export const MATCH_TITLE: Record<MatchKind, string> = {
  as_recommended: "a set of the solve before it held the same add with the same drop",
  differently: "a set of the solve before it added the same player for another drop, or dropped the same player for another add",
  not_recommended: "no set of the solve before it named either player",
  no_entry: "nothing was logged before it",
};
export const HORIZON_SHORT: Record<MoveHorizon, string> = { week: "week", three: "3 wk" };

/** The horizon a move is judged on: the one its set was recommended for (the week's set and
 * the streaming plan's, the week; the three weeks' set and the strategy's, the three weeks); a
 * move with no projection of its own, its week. */
export function moveHorizon(m: ProgressMove): MoveHorizon {
  const set = m.projected?.set;
  return set == null || set === "week" || set === "plan" ? "week" : "three";
}

/** A move on its horizon: its value projected and realized (in its league's units), whether the
 * realized span is over, and the gap once it is. */
export interface MoveFigures {
  horizon: MoveHorizon;
  projected: number | null;
  realized: number | null;
  complete: boolean;
  delta: number | null;
}

export function moveFigures(m: ProgressMove): MoveFigures {
  const horizon = moveHorizon(m);
  const projected = m.projected?.value.horizons[horizon]?.value ?? null;
  const span = m.realized?.valued ? m.realized.horizons[horizon] : undefined;
  const realized = span?.value ?? null;
  const complete = !!span?.complete;
  return { horizon, projected, realized, complete, delta: projected != null && realized != null && complete ? round(realized - projected) : null };
}

/** A move's key, the same from one read to the next. */
export function moveKey(m: ProgressMove): string {
  return `${m.league}:${m.at ?? m.day ?? ""}:${m.add ?? ""}:${m.drop ?? ""}`;
}

/** The moves of a scope (the public leagues', or one league's) over a week range, by match. */
export function scopeMoves(p: ProgressPayload, scope: string, from = 1, to = Infinity, match: MatchFilter = "all"): ProgressMove[] {
  return p.moves.filter((m) => (scope === POOLED ? m.public : m.league === scope) && m.week >= from && m.week <= to && (match === "all" || m.match.kind === match));
}

export function matchCounts(moves: ProgressMove[]): Record<MatchKind, number> {
  const out: Record<MatchKind, number> = { as_recommended: 0, differently: 0, not_recommended: 0, no_entry: 0 };
  for (const m of moves) out[m.match.kind] += 1;
  return out;
}

/** Some moves' totals: by scoring, the ones projected and realized over a complete horizon
 * summed (``compared``), the others realized so far or not at all; and the FAAB paid. */
export interface MovesTotals {
  made: number;
  compared: Partial<Record<Scoring, MovesSum>>;
  soFar: number;
  unscored: number;
  paid: number;
  bids: number;
}

export function movesTotals(moves: ProgressMove[]): MovesTotals {
  const out: MovesTotals = { made: moves.length, compared: {}, soFar: 0, unscored: 0, paid: 0, bids: 0 };
  for (const m of moves) {
    const f = moveFigures(m);
    const s = m.scoring ?? "categories";
    if (f.delta != null) {
      out.compared[s] = addMoves(out.compared[s], { moves: 1, projected: f.projected!, realized: f.realized!, same_way: Math.sign(f.realized!) === Math.sign(f.projected!) ? 1 : 0, share: null });
    } else if (f.realized != null) out.soFar += 1;
    else out.unscored += 1;
    if (m.bid) {
      out.paid += m.bid;
      out.bids += 1;
    }
  }
  return out;
}

/** The compared moves of one scoring summed to each week: realized against projected. */
export function movesTrend(moves: ProgressMove[], weeks: number[], scoring: Scoring): { week: number; projected: number; realized: number }[] {
  let projected = 0;
  let realized = 0;
  return weeks.map((week) => {
    for (const m of moves) {
      if (m.week !== week || (m.scoring ?? "categories") !== scoring) continue;
      const f = moveFigures(m);
      if (f.delta == null) continue;
      projected += f.projected!;
      realized += f.realized!;
    }
    return { week, projected: round(projected), realized: round(realized) };
  });
}

/** A move's value by category on its horizon, projected against realized, the largest first;
 * with how many came in above their projection. */
export function moveCats(m: ProgressMove): { rows: { cat: string; projected: number | null; realized: number | null }[]; above: number; both: number } {
  const h = moveHorizon(m);
  const proj = m.projected?.value.horizons[h]?.cats ?? {};
  const real = (m.realized?.valued ? m.realized.horizons[h]?.cats : null) ?? {};
  const cats = [...new Set([...Object.keys(proj), ...Object.keys(real)])];
  const rows = cats
    .map((cat) => ({ cat, projected: proj[cat] ?? null, realized: real[cat] ?? null }))
    .sort((a, b) => Math.abs(b.realized ?? b.projected ?? 0) - Math.abs(a.realized ?? a.projected ?? 0));
  const both = rows.filter((r) => r.projected != null && r.realized != null);
  return { rows, above: both.filter((r) => r.realized! > r.projected!).length, both: both.length };
}

/** The time a decision log entry was solved, from its id ("20261027T130000…-moves-bbm"). */
export function entryTime(id: string | null | undefined): string | null {
  const t = id?.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})/);
  return t ? `${t[1]}-${t[2]}-${t[3]} ${t[4]}:${t[5]}` : null;
}

// ---------------------------------------------------------------- the odds (PR 3)
/** The category odds' buckets summed over some pooled weeks: each bucket's count, mean odds and
 * share won, weighted by its count. */
export function bucketsOver(weeks: PooledWeek[], from = 1, to = Infinity): CalibrationBucket[] {
  const sums = new Map<number, { from: number; to: number; count: number; odds: number; won: number }>();
  for (const w of weeks) {
    if (w.week < from || w.week > to) continue;
    w.buckets.forEach((b, i) => {
      const s = sums.get(i) ?? { from: b.from, to: b.to, count: 0, odds: 0, won: 0 };
      if (b.count && b.odds != null && b.won != null) {
        s.count += b.count;
        s.odds += b.odds * b.count;
        s.won += b.won * b.count;
      }
      sums.set(i, s);
    });
  }
  return [...sums.entries()]
    .sort(([a], [b]) => a - b)
    .map(([, s]) => ({ from: s.from, to: s.to, count: s.count, odds: s.count ? round(s.odds / s.count) : null, won: s.count ? round(s.won / s.count) : null }));
}

/** The weeks a view shows: the range chosen cut to the scope's recorded weeks, or all of them
 * when none is chosen or the cut leaves none; [1, 0] with no week recorded. */
export function shownRange(bounds: [number, number] | null, range: [number, number] | null): [number, number] {
  if (!bounds) return [1, 0];
  if (!range) return bounds;
  const r: [number, number] = [Math.max(range[0], bounds[0]), Math.min(range[1], bounds[1])];
  return r[0] <= r[1] ? r : bounds;
}
