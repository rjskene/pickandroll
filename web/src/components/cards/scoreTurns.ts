import type { PickRow, Score, ScoreEntry } from "../../api";

/** Whether a solve's board was one of my real turns: on the clock by the snake, and the pick at
 * that overall made by my team or not made yet. A slot the snake calls mine that another team
 * picked at (a traded pick) is not my turn. */
export function turnFilter(picks: PickRow[] | undefined, myTeam: string): (h: ScoreEntry) => boolean {
  const madeBy = new Map((picks ?? []).map((p) => [p.overall, p.team]));
  return (h) => h.on_the_clock && (madeBy.get(h.next_overall) ?? myTeam) === myTeam;
}

/** One point of the score chart: before pick 1, each of my real turns, then the latest solve
 * while the draft is on, or the final roster once it is full. */
export interface ScorePoint {
  key: string;
  kind: "pre" | "turn" | "now" | "final";
  /** The overall on the clock for that solve; null for the final roster. */
  overall: number | null;
  wins: number;
  value: number;
  matchups: number;
  /** The model that produced it; null for the final roster (its drafted players' own odds). */
  mode: ScoreEntry["mode"] | null;
  entry: ScoreEntry | null;
}

const point = (kind: ScorePoint["kind"], h: ScoreEntry): ScorePoint => ({
  key: `${kind}-${h.version}`,
  kind,
  overall: h.next_overall,
  wins: h.wins,
  value: h.value,
  matchups: h.matchups,
  mode: h.mode,
  entry: h,
});

/** The chart's points in draft order. Each real turn is its last solve (a keeper change can
 * re-solve the same board), left out when it is the benchmark's own solve (my first turn's board
 * is usually the benchmark); the latest solve is added while it is not already shown. */
export function scorePoints(sc: Score, isTurn: (h: ScoreEntry) => boolean): ScorePoint[] {
  const out: ScorePoint[] = [];
  if (sc.benchmark) out.push(point("pre", sc.benchmark));
  const turns = new Map<number, ScoreEntry>();
  for (const h of sc.history) if (isTurn(h)) turns.set(h.next_overall, h);
  const shown = [...turns.values()].filter((h) => h.version !== sc.benchmark?.version).sort((a, b) => a.next_overall - b.next_overall);
  for (const h of shown) out.push(point("turn", h));
  if (sc.final) {
    out.push({ key: "final", kind: "final", overall: null, wins: sc.final.wins, value: sc.final.value, matchups: sc.final.matchups, mode: null, entry: null });
  } else if (sc.latest) {
    const v = sc.latest.version;
    if (v !== sc.benchmark?.version && !shown.some((h) => h.version === v)) out.push(point("now", sc.latest));
  }
  return out;
}
