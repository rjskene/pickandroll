// Thin typed client for the pickandroll API. Vite proxies /api to the FastAPI server.

export type Cat = "pts" | "threes" | "reb" | "ast" | "stl" | "blk" | "tov" | "fg_pct" | "ft_pct";
export const CATS: Cat[] = ["pts", "threes", "reb", "ast", "stl", "blk", "tov", "fg_pct", "ft_pct"];
export const CAT_LABEL: Record<Cat, string> = {
  pts: "PTS", threes: "3PM", reb: "REB", ast: "AST", stl: "STL", blk: "BLK", tov: "TO", fg_pct: "FG%", ft_pct: "FT%",
};

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
}

export interface BoardPlayer {
  player_id: string;
  name: string;
  team: string;
  positions: string;
  games: number;
  z: Record<Cat, number>;
  total: number;
  taken: boolean;
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
  punted?: string;
  p_available_first?: number;
  p_available_next?: number;
  min_active_total: number;
}

export interface PlanRow {
  pick: number;
  player: string;
  name: string;
  availability: number;
}

export interface Recommendation {
  version: number;
  mode: "horizon" | "roster";
  on_the_clock: boolean;
  next_overall: number;
  my_next_pick: number | null;
  adp_source: string;
  candidates: Candidate[];
  punted: Cat[];
  plan: PlanRow[];
  punt_scan: PuntScanRow[];
  timings: Record<string, number>;
  best_roster: {
    objective: number;
    punted: Cat[];
    min_active_total: number;
    cat_totals: Record<Cat, number>;
    roster: { player: string; name: string; slot: string; slot_index: number }[];
    solve_seconds: number;
  };
}

export interface PuntScanRow {
  punt: string;
  objective: number;
  gap_to_best: number;
  min_active_total: number;
  roster: string[];
}

export interface SolveEvent {
  stage: "start" | "punt_scan" | "plan" | "candidates" | "roster" | "done" | "error";
  done: number;
  total: number;
  elapsed_ms: number;
  auto_punt?: boolean;
  punt?: string;
  objective?: number;
  best_punt?: string;
  best_objective?: number;
  first_pick?: string;
  first_pick_name?: string;
  candidate?: Candidate & { failed?: boolean };
  message?: string;
}

export interface RecommendParams {
  n: number;
  punt: Cat[] | null;
  max_punts: number;
  balance: number;
  horizon: boolean;
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
  projections: () => request<{ file: string; kind: string; modified: string }[]>("/projections"),
  sessions: () => request<SessionSummary[]>("/sessions"),
  session: (id: string) => request<SessionSummary>(`/sessions/${id}`),
  createSession: (body: {
    projection_file: string;
    num_teams: number;
    my_position: number;
    my_team: string;
    bench: number;
    positions_file: string | null;
    adp_file: string | null;
  }) => request<SessionSummary>("/sessions", { method: "POST", body: JSON.stringify(body) }),
  board: (id: string, limit = 300) =>
    request<{ version: number; players: BoardPlayer[] }>(`/sessions/${id}/board?limit=${limit}`),
  picks: (id: string) => request<PickRow[]>(`/sessions/${id}/picks`),
  addPick: (id: string, body: { team: string; player_id: string }) =>
    request<PickRow>(`/sessions/${id}/picks`, { method: "POST", body: JSON.stringify(body) }),
  undoPick: (id: string) => request<PickRow>(`/sessions/${id}/picks/last`, { method: "DELETE" }),
  recommend: (id: string, params: RecommendParams) =>
    request<Recommendation>(`/sessions/${id}/recommend`, { method: "POST", body: JSON.stringify(params) }),
  eventsUrl: (id: string) => `${BASE}/sessions/${id}/events`,
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
