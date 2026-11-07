// The History screen's words and filters (#334). Pure, so `npm test` runs it under Node.
import type { HistoryPayload, HistoryRow, HistoryStep } from "./api";
import { dayLabel, gainLabel } from "./season.ts";

export type Namer = (id: number | null | undefined) => string;

export const KIND_WORDS: Record<HistoryRow["kind"], string> = {
  claim: "claim",
  free_agent: "free agent",
  drop: "drop",
  trade: "trade",
  comeback: "comeback",
  il: "IL move",
};

/** A result's tone on the row; "" for none. */
export const RESULT_TONE: Record<HistoryRow["result"], string> = {
  won: "good",
  landed: "good",
  lost: "bad",
  lapsed: "bad",
  partial: "bad",
  "by hand": "",
  pending: "",
};

export interface HistoryFilter {
  league: string | null;
  kind: HistoryRow["kind"] | null;
  result: HistoryRow["result"] | null;
}

export const NO_FILTER: HistoryFilter = { league: null, kind: null, result: null };

export function filterRows(rows: HistoryRow[], f: HistoryFilter): HistoryRow[] {
  return rows.filter(
    (r) => (f.league === null || r.league === f.league) && (f.kind === null || r.kind === f.kind) && (f.result === null || r.result === f.result),
  );
}

/** The add and the drop, the trade's sides, or who came back or moved, in a line. */
export function moveLine(r: HistoryRow, name: Namer): string {
  if (r.kind === "trade") {
    const side = (word: "got" | "gave") => (r.sides ?? []).filter((s) => s.side === word).map((s) => s.name);
    const [got, gave] = [side("got"), side("gave")];
    if (got.length || gave.length) return [got.length ? `got ${got.join(", ")}` : "", gave.length ? `gave ${gave.join(", ")}` : ""].filter(Boolean).join(" · ");
    return (r.sides ?? []).map((s) => s.name).join(", ");
  }
  if (r.kind === "comeback") return `${name(r.player)} back · −${name(r.drop)}`;
  if (r.kind === "il") return `${name(r.player)} to ${r.why.need && typeof r.why.need === "object" ? r.why.need.slot : "IL"}`;
  return [r.add != null ? `+${name(r.add)}` : "", r.drop != null ? `−${name(r.drop)}` : ""].filter(Boolean).join(" · ");
}

function setWords(key: string | null | undefined): string {
  if (key === "three") return "the three weeks' set";
  if (key === "week_plan") return "the week plan";
  if (key === "week") return "the week's set";
  return key ? `the ${key} set` : "a set no longer on the log";
}

function odds(p: number): string {
  return `${Math.round(100 * p)}%`;
}

function gains(week: number | null | undefined, three: number | null | undefined, season?: number | null): string | null {
  const parts = [
    week != null ? `${gainLabel(week)} this week` : "",
    three != null ? `${gainLabel(three)} over the three weeks` : "",
    season != null ? `${gainLabel(season)} to the season's end` : "",
  ].filter(Boolean);
  return parts.length ? `Gain: ${parts.join(", ")}.` : null;
}

function stepLine(s: HistoryStep, name: Namer): string {
  const words = s.words ? `: ${s.words}` : "";
  return `${s.stage} ${name(s.player)}, ${s.outcome ?? "no outcome"}${words}`;
}

const MATCH_WORDS: Record<string, string> = {
  as_recommended: "Made as recommended, by hand.",
  differently: "Made differently from the latest recommendation.",
  not_recommended: "Not among the latest recommendation's moves.",
};

/** Why a row happened, a line each: what the screen's expanded row says. */
export function whyLines(r: HistoryRow, name: Namer): string[] {
  const w = r.why;
  const steps = (w.steps ?? []).map((s) => stepLine(s, name));
  if (w.note) return [w.note];
  if (r.kind === "comeback" || r.kind === "il") {
    const need = typeof w.need === "string" ? w.need : w.need ? `It opened a spot for the claim on ${name(w.need.for)}.` : "No claim on the log asked for it.";
    return [need, ...steps];
  }
  if (w.match) {
    const said = w.move ? `It said ${[`+${name(w.move.add)}`, w.move.drop != null ? `−${name(w.move.drop)}` : ""].filter(Boolean).join(" · ")}, from ${setWords(w.set)}.` : null;
    return [MATCH_WORDS[w.match] ?? w.match, said, gains(w.week, w.three)].filter((x): x is string => !!x);
  }
  const from = w.step != null ? `Step ${w.step} of ${w.steps_of} of the week plan.` : `From ${setWords(w.set)}.`;
  const matchup = w.matchup != null ? `Matchup odds when logged: ${odds(w.matchup)}${w.against != null ? `, against ${odds(w.against)} with the three weeks' set` : ""}.` : null;
  return [from, gains(w.week, w.three, w.season), matchup, w.bid_reason ? `Bid: ${w.bid_reason}.` : null].filter((x): x is string => !!x);
}

export function bidText(bid: number | null): string {
  return bid == null ? "" : `$${bid}`;
}

/** The landing's History row: how many moves are on record and the latest one's day, plus any
 * league the record could not read. */
export function historyFoldLine(p: HistoryPayload): string {
  const n = p.rows.length;
  const latest = p.rows.reduce<string | null>((best, r) => (r.date && (!best || r.date > best) ? r.date : best), null);
  const skipped = p.skipped.length;
  return [
    n ? `${n} move${n === 1 ? "" : "s"}` : "no moves on record yet",
    latest ? `latest ${dayLabel(latest)}` : null,
    skipped ? `${skipped} league${skipped === 1 ? "" : "s"} not read` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}
