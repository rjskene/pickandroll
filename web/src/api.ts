// Thin typed client for the pickandroll API. Vite proxies /api to the FastAPI server.

export type Cat = "pts" | "threes" | "reb" | "ast" | "stl" | "blk" | "tov" | "fg_pct" | "ft_pct";
export const CATS: Cat[] = ["pts", "threes", "reb", "ast", "stl", "blk", "tov", "fg_pct", "ft_pct"];
export const CAT_LABEL: Record<Cat, string> = {
  pts: "PTS", threes: "3PM", reb: "REB", ast: "AST", stl: "STL", blk: "BLK", tov: "TO", fg_pct: "FG%", ft_pct: "FT%",
};

export type Objective = "win" | "sum";
export type Scale = "wins" | "z";
export type WinLabel = "conceded" | "contested" | "secured";

export interface CurveSpec {
  mu: Record<Cat, number>;
  sigma: Record<Cat, number>;
  breaks: number[];
  source: string;
}

export interface SurvivalStatus {
  mode: "none" | "simulate" | "file";
  status: "none" | "building" | "ready" | "failed";
  sims?: number;
  done?: number;
  source?: string | null;
  error?: string;
  seconds?: number;
  drafters?: string[];
}

export interface SolverStatus {
  enabled: boolean;
  running: boolean;
  pending: boolean;
  runs: number;
  solved_version: number | null;
  last_started: string | null;
  last_finished: string | null;
  last_error: string | null;
  recommendation_version: number | null;
}

export interface SessionSummary {
  id: string;
  version: number;
  projection: string;
  num_teams: number;
  roster_size: number;
  cats: Cat[];
  slots: string[];
  my_team: string;
  my_position: number;
  my_picks: number[];
  picks_made: number;
  next_overall: number;
  my_next_pick: number | null;
  on_the_clock: boolean;
  complete: boolean;
  my_roster: string[];
  unknown_positions: number;
  adp_source: string;
  adp_known: number;
  objective: Objective;
  curve: CurveSpec | null;
  sigma_scale: number;
  availability_source: "adp" | "survival";
  survival: SurvivalStatus;
  solver: SolverStatus;
}

export interface BoardPlayer {
  player_id: string;
  name: string;
  team: string;
  positions: string;
  games: number;
  adp: number | null;
  p_next: number | null;
  /** First-order cost of taking this player with my next pick instead of the plan's choice. */
  cost: number | null;
  z: Record<Cat, number>;
  total: number;
  taken: boolean;
}

export interface BoardResponse {
  version: number;
  next_pick: number | null;
  prices_version: number | null;
  scale: Scale | null;
  players: BoardPlayer[];
}

export type SimStrategy = "z" | "adp" | "lp";

export interface AutoPickParams {
  count?: number | null;
  until_my_pick?: boolean;
  noise?: number;
  seed?: number | null;
  strategy?: SimStrategy;
}

export interface PickRow {
  overall: number;
  round: number;
  position: number;
  team: string;
  player_id: string;
  name: string;
}

export interface Candidate {
  player: string;
  name: string;
  objective: number;
  cost_vs_best: number;
  cost_first_order: number | null;
  p_available_first?: number;
  p_available_next?: number;
  min_active_total: number;
  time_limited?: boolean;
}

export interface PlanRow {
  pick: number;
  player: string;
  name: string;
  availability: number;
}

export interface CategoryRow {
  cat: Cat;
  drafted: number;
  expected: number;
  odds: number;
  label: WinLabel;
  slope: number;
  beaten_now: number;
  beaten_expected: number;
  mu: number;
  sigma: number;
}

export interface Opponent {
  team: string;
  cats_beaten: number;
  won: boolean;
  leads: Cat[];
}

export interface League {
  opponents: Opponent[];
  matchups_won: number;
  cats_beaten: number;
  teams_beaten: Record<Cat, number>;
}

export interface Scenario {
  gone: string;
  gone_name: string;
  pick: string | null;
  pick_name: string | null;
  objective: number;
  wins: number | null;
  time_limited: boolean;
}

export interface ScoreEntry {
  version: number;
  next_overall: number;
  my_pick: number | null;
  on_the_clock: boolean;
  mode: "horizon" | "roster";
  wins: number;
  value: number;
  matchups: number;
  top: string | null;
  drafted: number;
  at: string;
}

export interface Recommendation {
  version: number;
  on_the_clock: boolean;
  next_overall: number;
  my_next_pick: number | null;
  drafted: number;
  mode: "horizon" | "roster";
  objective: Objective;
  scale: Scale;
  fallback: string | null;
  timings: Record<string, number>;
  adp_source: string;
  availability_source: "adp" | "survival";
  candidates: Candidate[];
  plan: PlanRow[];
  scenarios: Scenario[];
  best_roster: {
    objective: number;
    wins: number;
    value: number;
    min_active_total: number;
    cat_totals: Record<Cat, number>;
    roster: { player: string; name: string; slot: string; slot_index: number; locked?: boolean }[];
    solve_seconds: number;
    time_limited: boolean;
  };
  categories: CategoryRow[];
  league: League;
  wins: number;
  value: number;
  score: ScoreEntry;
}

export interface RecommendationResponse {
  version: number;
  solved_version: number | null;
  stale: boolean;
  solver: SolverStatus;
  recommendation: Recommendation | null;
}

export interface FinalScore {
  wins: number;
  value: number;
  matchups: number;
  cats_beaten: number;
  opponents: Opponent[];
  categories: CategoryRow[];
}

export interface Score {
  version: number;
  objective: Objective;
  benchmark: ScoreEntry | null;
  best: ScoreEntry | null;
  latest: ScoreEntry | null;
  final: FinalScore | null;
  drafted: number;
  roster_size: number;
  drafted_wins: number;
  drafted_value: number;
  current_wins: number | null;
  vs_benchmark: number | null;
  vs_best: number | null;
  history: ScoreEntry[];
}

export interface TeamRow {
  team: string;
  position: number;
  picks: number;
  mine: boolean;
  totals: Record<Cat, number>;
  projected: Record<Cat, number>;
  cats_beaten: number | null;
  won: boolean | null;
  leads: Cat[];
}

export interface TeamsResponse {
  version: number;
  cats: Cat[];
  my_final_from: "plan" | "replacement fill";
  teams: TeamRow[];
  matchups_won: number;
  cats_beaten: number;
  teams_beaten: Record<Cat, number>;
}

export interface SolveEvent {
  stage: "start" | "plan" | "prices" | "candidates" | "scenarios" | "roster" | "done" | "error";
  done: number;
  total: number;
  elapsed_ms: number;
  version?: number;
  /** The objective's name on the start event, the plan's objective value on the plan event. */
  objective?: Objective | number;
  wins?: number | null;
  first_pick?: string;
  first_pick_name?: string;
  time_limited?: boolean;
  fallback?: string | null;
  prices?: Record<string, number | null>;
  candidate?: Candidate & { failed?: boolean };
  gone?: string;
  gone_name?: string;
  message?: string;
}

export interface SurvivalEvent {
  status: "building" | "ready" | "failed";
  done?: number;
  total?: number;
  sims?: number;
  seconds?: number;
  error?: string;
}

export interface SolveParams {
  n: number;
  horizon: boolean;
  scenarios: number;
  objective: Objective | null;
}

export interface SessionCreateBody {
  projection_file: string;
  num_teams: number;
  my_position: number;
  my_team: string;
  bench: number;
  positions_file: string | null;
  adp_file: string | null;
  objective: Objective;
  sigma_scale: number;
  curve_file: string | null;
  survival: "none" | "simulate" | "file";
  survival_sims: number;
  survival_file: string | null;
  solve_ahead: boolean;
  time_limit: number;
}

export interface FileEntry {
  file: string;
  kind: string;
  modified: string;
}

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* keep statusText */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export const api = {
  projections: () => request<FileEntry[]>("/projections"),
  files: (kind: "survival" | "curve") => request<FileEntry[]>(`/files?kind=${kind}`),
  sessions: () => request<SessionSummary[]>("/sessions"),
  session: (id: string) => request<SessionSummary>(`/sessions/${id}`),
  createSession: (body: SessionCreateBody) => request<SessionSummary>("/sessions", { method: "POST", body: JSON.stringify(body) }),
  board: (id: string, limit = 300) => request<BoardResponse>(`/sessions/${id}/board?limit=${limit}`),
  picks: (id: string) => request<PickRow[]>(`/sessions/${id}/picks`),
  addPick: (id: string, body: { team: string; player_id: string }) =>
    request<PickRow>(`/sessions/${id}/picks`, { method: "POST", body: JSON.stringify(body) }),
  undoPick: (id: string) => request<PickRow>(`/sessions/${id}/picks/last`, { method: "DELETE" }),
  autopick: (id: string, body: AutoPickParams) =>
    request<{ added: PickRow[]; version: number }>(`/sessions/${id}/autopick`, { method: "POST", body: JSON.stringify(body) }),
  /** Queue a background solve; the result arrives as a `recommendation` event. */
  solve: (id: string, params: SolveParams) =>
    request<{ queued: boolean; version: number; solver: SolverStatus }>(`/sessions/${id}/solve`, { method: "POST", body: JSON.stringify(params) }),
  recommendation: (id: string) => request<RecommendationResponse>(`/sessions/${id}/recommendation`),
  teams: (id: string) => request<TeamsResponse>(`/sessions/${id}/teams`),
  score: (id: string) => request<Score>(`/sessions/${id}/score`),
  eventsUrl: (id: string) => `${BASE}/sessions/${id}/events`,
  yahooStatus: (id: string) => request<{ attached: boolean; running?: boolean; league?: string; polls?: number; last_error?: string | null }>(`/sessions/${id}/yahoo`),
};

export function teamLabel(session: SessionSummary, position: number): string {
  return position === session.my_position ? session.my_team : `Team ${position}`;
}

export function pickOwner(numTeams: number, overall: number): { round: number; position: number } {
  const round = Math.floor((overall - 1) / numTeams);
  const idx = (overall - 1) % numTeams;
  const position = round % 2 === 0 ? idx + 1 : numTeams - idx;
  return { round: round + 1, position };
}
