/** The freshness light (#153): the dot's state and word, its hover line and its sheet's rows,
 * from `GET /seasons/status`. Pure: the dot and the sheet only show what these give. */
import type { BuiltRow, ExportRow, RoutineRow, StatusLeague, StatusPayload, StatusRow, StatusState, YahooRow } from "./api";

const RANK: StatusState[] = ["green", "amber", "red"];

/** The word beside the dot: its state is never told by colour alone. */
export const STATE_WORD: Record<StatusState, string> = { green: "up to date", amber: "pending", red: "failed" };
/** The dot's class, on the shared tokens: good, accent (warning), bad. */
export const STATE_TONE: Record<StatusState, string> = { green: "good", amber: "accent", red: "bad" };

const KIND_LABEL: Record<string, string> = {
  routine: "daily run",
  refresh: "last refresh",
  matchup: "matchup page",
  lineup: "lineup page",
  schedule: "schedule page",
  transactions: "transactions page",
  moves: "waiver moves",
  plan: "streaming plan",
  strategy: "strategy run",
  trades: "trade evaluation",
};

export interface SheetRow {
  key: string;
  label: string;
  /** When it was read, built or ran ("05:14", or with its day when not today); "—" for none. */
  time: string;
  /** What it is or rests on: the file, the steps, the inputs' times. */
  detail: string | null;
  /** None for what is made on request. */
  state: StatusState | null;
  reason: string;
}

export interface SheetSection {
  title: string;
  state: StatusState;
  rows: SheetRow[];
}

/** The worst of the states, none left out; green when none is left. */
export function worstOf(states: (StatusState | null | undefined)[]): StatusState {
  return RANK[Math.max(0, ...states.map((s) => (s ? RANK.indexOf(s) : 0)))];
}

const hhmm = (d: Date) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;

/** "05:14" on the viewer's clock when it is ``now``'s day, "Oct 22 05:14" otherwise; "—" for none. */
export function when(iso: string | null | undefined, now: Date): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  if (d.toDateString() === now.toDateString()) return hhmm(d);
  return `${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })} ${hhmm(d)}`;
}

export function leagueOf(p: StatusPayload | undefined, league: string): StatusLeague | undefined {
  return p?.leagues.find((l) => l.league === league);
}

function row(r: StatusRow, at: string | null, detail: string | null, now: Date, label?: string): SheetRow {
  return { key: r.kind, label: label ?? KIND_LABEL[r.kind] ?? r.kind, time: when(at, now), detail, state: r.state, reason: r.reason };
}

function routineRow(r: RoutineRow, now: Date): SheetRow {
  const steps = Object.entries(r.steps ?? {}).map(([k, s]) => `${k} ${s.status ?? "?"}${s.status !== "ok" && s.detail ? ` (${s.detail})` : ""}`);
  return row(r, r.finished_at ?? r.started_at, steps.length ? steps.join(" · ") : null, now);
}

/** A refresh job in words: "last job done 47/47, 14:19 to 14:20", or the step it stopped at. */
export function jobText(r: YahooRow, now: Date): string | null {
  if (!r.status) return null;
  const where = r.step && r.step !== "done" ? ` at ${r.step}` : "";
  const counts = r.total ? ` ${r.done ?? 0}/${r.total}` : "";
  const span = r.status === "running" ? `, since ${when(r.started_at, now)}` : `, ${when(r.started_at, now)} to ${when(r.finished_at, now)}`;
  return `last job ${r.status}${where}${counts}${span}${r.logged ? " (from its log)" : ""}`;
}

function yahooRow(r: YahooRow, now: Date): SheetRow {
  const notes = [jobText(r, now), r.error, ...Object.values(r.warnings ?? {})].filter((x): x is string => Boolean(x));
  if (r.kind === "refresh") notes.push(r.snapshot_at ? `snapshot ${when(r.snapshot_at, now)}` : "no snapshot saved");
  return row(r, r.read_at, notes.length ? notes.join(" · ") : null, now);
}

function builtRow(r: BuiltRow, now: Date): SheetRow {
  if (r.kind === "trades") {
    const inputs = Object.entries(r.inputs ?? {}).map(([k, at]) => `${k} ${when(at, now)}`);
    return row(r, null, inputs.join(" · ") || null, now);
  }
  const on = [r.system, r.projection_file].filter(Boolean).join(", ");
  return row(r, r.built_at, on || null, now);
}

/** The sheet's sections for a league: the daily run and the exports every league shares, then
 * its Yahoo reads and its recommendations. */
export function sheetSections(p: StatusPayload, league: string, now: Date): SheetSection[] {
  const l = leagueOf(p, league);
  const out: SheetSection[] = [
    { title: "Daily run", state: p.routine.state ?? "green", rows: [routineRow(p.routine, now)] },
    { title: "Basketball Monster", state: p.exports.state, rows: p.exports.rows.map((r: ExportRow) => row(r, r.as_of, r.file, now, r.label)) },
  ];
  if (l?.yahoo) out.push({ title: l.public ? "Yahoo" : "Yahoo, read by the extension", state: l.yahoo.state, rows: l.yahoo.rows.map((r) => yahooRow(r, now)) });
  if (l?.recommendations) out.push({ title: "Recommendations", state: l.recommendations.state, rows: l.recommendations.rows.map((r) => builtRow(r, now)) });
  return out;
}

/** A league's light: its own state and the daily run's, which feeds every league; amber for a
 * league the status does not list yet; none before the status reads. */
export function lightOf(p: StatusPayload | undefined, league: string): StatusState | null {
  if (!p) return null;
  const l = leagueOf(p, league);
  return worstOf([l?.state ?? "amber", p.routine.state]);
}

/** The hover line: when everything is in, when the updates landed and when the moves were
 * solved; otherwise what to look at, red first. */
export function statusLine(p: StatusPayload, league: string, now: Date): string {
  const l = leagueOf(p, league);
  if (!l) return "no status for this league yet";
  if (l.error) return l.error;
  const rows = sheetSections(p, league, now).flatMap((s) => s.rows.map((r) => ({ ...r, section: s.title })));
  const late = [...rows.filter((r) => r.state === "red"), ...rows.filter((r) => r.state === "amber")];
  if (late.length) {
    const named = late.slice(0, 2).map((r) => `${r.label}: ${r.reason}`);
    return `${late.length} to look at: ${named.join("; ")}${late.length > 2 ? `; ${late.length - 2} more` : ""}`;
  }
  const landed = latest([p.routine.finished_at, ...p.exports.rows.map((r) => r.as_of), ...(l.yahoo?.rows ?? []).map((r) => r.read_at)]);
  const moves = l.recommendations?.rows.find((r) => r.kind === "moves")?.built_at ?? null;
  return `all updates landed ${when(landed, now)}; recommendations ${when(moves, now)}`;
}

/** The newest of ISO times (they may carry different offsets). */
function latest(xs: (string | null | undefined)[]): string | null {
  let out: string | null = null;
  for (const x of xs) if (x && !Number.isNaN(Date.parse(x)) && (out === null || Date.parse(x) > Date.parse(out))) out = x;
  return out;
}
