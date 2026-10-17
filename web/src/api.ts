// Thin typed client for the pickandroll API. Vite proxies /api to the FastAPI server.

/** The nine categories, and a points league's one: fpts, the league's weights over the stats. */
export type Cat = "pts" | "threes" | "reb" | "ast" | "stl" | "blk" | "tov" | "fg_pct" | "ft_pct" | "fpts";
export const CATS: Cat[] = ["pts", "threes", "reb", "ast", "stl", "blk", "tov", "fg_pct", "ft_pct"];
export const CAT_LABEL: Record<Cat, string> = {
  pts: "PTS", threes: "3PM", reb: "REB", ast: "AST", stl: "STL", blk: "BLK", tov: "TO", fg_pct: "FG%", ft_pct: "FT%", fpts: "FPTS",
};
/** A points league's session: its one category is fpts. */
export const isPoints = (cats: readonly Cat[]): boolean => cats.length === 1 && cats[0] === "fpts";

export type Objective = "win" | "sum";
export type Scale = "wins" | "z";
export type WinLabel = "conceded" | "contested" | "secured";

export interface CurveSpec {
  mu: Record<Cat, number>;
  sigma: Record<Cat, number>;
  breaks: number[];
  source: string;
}

export type SurvivalMode = "none" | "simulate" | "file" | "league";
/** Where the win curve's μ and σ come from without a curve file: the simulated league, or the
 * league's own drafted rosters on the projections (#65). */
export type CurveChoice = "simulated" | "league";
/** curve=league: the seasons fitted, those left out and why, and the standings' σ in z units
 * (null for a category the standings cannot convert: the percentages). */
export interface CurveFit {
  /** A draft of the shared archive (#77) names its league too. */
  seasons: { year: number; league?: string; rosters: number; picks: number; scored: number; unmatched: string[] }[];
  skipped: { year: number; league?: string; reason: string }[];
  check: Partial<Record<Cat, number | null>>;
  check_seasons: string[];
}
/** The ADP model's spread of a draft slot, SPREAD.base + SPREAD.growth × ADP picks, fitted on the
 * league's nine drafts, for the setup's text. A session reports the values it runs on. */
// Mirrors SPREAD_BASE / SPREAD_GROWTH in src/pickandroll/availability/adp.py: change both.
export const SPREAD = { base: 1.5, growth: 0.15 } as const;
/** A league table answers from this keeper-adjusted ADP on; earlier players keep the normal model. */
// Mirrors LEAGUE_FROM_ADP in src/pickandroll/availability/league.py: change both.
export const LEAGUE_FROM_ADP = 90;
/** The league table a session that names no survival uses, when data/ holds it (else it simulates). */
// Mirrors LEAGUE_SURVIVAL_DEFAULT in src/pickandroll/api/app.py: change both.
export const LEAGUE_SURVIVAL_DEFAULT = "yahoo_history/survival_by_adp_adjusted.csv";
export type AvailabilitySource = "adp" | "survival" | "league";
/** The league's shift of the ADP formula by keeper-adjusted ADP (#64): the table's file and fit. */
export interface AvailabilityBias {
  source: string | null;
  from_adp: number;
  half_life: number | null;
  seasons: number[];
  target: number | null;
}
export type AdpFrom = "market" | "rank" | "end" | "stand-in";

export interface SurvivalStatus {
  mode: SurvivalMode;
  status: "none" | "building" | "ready" | "failed";
  sims?: number;
  done?: number;
  source?: string | null;
  error?: string;
  seconds?: number;
  drafters?: string[];
  /** A league table: it answers from ADP from_adp to max_adp; the ADP model covers the rest. */
  from_adp?: number;
  max_adp?: number;
  /** The session named no survival and the league table could not serve it: why it simulates. */
  note?: string;
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

/** A keeper in the session's table, in draft order (docs/KEEPERS.md). */
export interface KeeperRow {
  position: number;
  round: number;
  overall: number;
  player_id: string;
  name: string;
  team: string;
  mine: boolean;
  /** His pick is in the log: the draft has reached his slot. */
  applied: boolean;
  /** The table named his pick outright (a traded pick): it does not move with the owner map. */
  by_overall: boolean;
}

/** A keeper as the API takes it: no position is mine; the player by id or by name. With traded
 * picks a team may hold two picks in a round or none: `overall` names the pick outright. */
export interface KeeperIn {
  position: number | null;
  round: number;
  overall?: number | null;
  player_id?: string | null;
  player?: string | null;
}

/** A games haircut in the session's table (#76): his totals are scaled to the games it leaves. */
export interface AdjustmentRow {
  player_id: string;
  name: string;
  team: string;
  /** As given: the share of his projected games he plays, or the games he misses. */
  games_fraction: number | null;
  games_out: number | null;
  note: string | null;
  /** The share of his projected games he keeps. */
  fraction: number;
  /** Projected games, and the games the haircut leaves him. */
  games: number;
  games_left: number;
  taken: boolean;
}

/** A haircut as the API takes it: the player by id or name; games out or a games fraction. A
 * haircut of nothing (no games out, a fraction of one) clears the player's. */
export interface AdjustmentIn {
  player_id?: string | null;
  player?: string | null;
  games_out?: number | null;
  games_fraction?: number | null;
  note?: string | null;
}

export interface SessionSummary {
  id: string;
  version: number;
  projection: string;
  num_teams: number;
  roster_size: number;
  cats: Cat[];
  slots: string[];
  /** The league folder the session was made from (data/leagues/<id>/), if any. */
  league: string | null;
  /** A points league's scoring: stat to points per unit. */
  points: Record<string, number> | null;
  my_team: string;
  my_position: number;
  /** My draftable picks: my keepers' rounds are not among them. */
  my_picks: number[];
  /** Every pick of mine (by the owner map, else the snake), keeper rounds included. */
  my_slots: number[];
  /** The draft position that owns each overall pick, pick 1 first; null is a pure snake. */
  pick_owners: number[] | null;
  /** The picks the owner map gives to another position than the snake's. */
  traded_picks: number[];
  keepers: KeeperRow[];
  /** Games haircuts (#76), and the league file's entries that were skipped. */
  adjustments: AdjustmentRow[];
  adjustments_note: string[];
  picks_made: number;
  next_overall: number;
  my_next_pick: number | null;
  on_the_clock: boolean;
  complete: boolean;
  my_roster: string[];
  unknown_positions: number;
  adp_source: string;
  adp_known: number;
  /** Players the ADP list lacks whose ADP is their rank mapped onto its scale, and the ranks'
   * source ("o_rank:<players file>" for Yahoo's own rank; null without one). */
  adp_fallback: number;
  adp_fallback_source: string | null;
  /** Keepers out of the market: each moves every player ranked behind him up a pick. */
  adp_keepers_ahead: number;
  /** The ADP model's spread of a draft slot: spread_base + spread_growth * ADP picks. */
  spread_base: number;
  spread_growth: number;
  objective: Objective;
  curve: CurveSpec | null;
  curve_fit?: CurveFit | null;
  sigma_scale: number;
  availability_source: AvailabilitySource;
  /** The ADP formula's shift, where the formula answers; null without a bias table. */
  availability_bias?: AvailabilityBias | null;
  survival: SurvivalStatus;
  solver: SolverStatus;
  /** The settings the next solve starts with: background, room and manual solves alike. */
  solve_params: SessionSolveParams;
}

/** The server's solve settings. A room sets its own budget (early, turn_time_limit, turn_n,
 * presolve); the candidate counts change with setSolveParams. */
export interface SessionSolveParams {
  /** Candidates priced exactly. */
  n: number;
  /** Candidates priced at my turn; null: n. */
  turn_n: number | null;
  horizon: boolean;
  scenarios: number;
  objective: Objective | null;
  early: boolean;
  turn_time_limit: number | null;
  presolve: boolean;
}

export interface BoardPlayer {
  player_id: string;
  name: string;
  team: string;
  positions: string;
  games: number;
  adp: number | null;
  /** ADP minus the keepers ranked ahead of him: where the market reaches him. */
  adp_eff: number | null;
  /** market: the ADP list; rank: his rank mapped onto its scale (he is not on the list); end:
   * neither knows him (past the end of the draft); stand-in: no rank source, a value rank. */
  adp_from: AdpFrom;
  keepers_ahead: number;
  p_next: number | null;
  /** Cost of taking this player with my next pick instead of the plan's choice: the exact
   * re-solve for priced candidates, else the first-order estimate from the plan's slopes. */
  cost: number | null;
  cost_exact: boolean;
  z: Record<Cat, number>;
  total: number;
  /** A points league's projected fantasy points over the projection's games. */
  fpts?: number | null;
  taken: boolean;
  /** The team that took him and its pick (a keeper's slot for a keeper); null while he is available. */
  taken_by: { team: string; overall: number } | null;
  /** The team keeping him, if he is a keeper. */
  keeper: string | null;
  /** His games haircut (#76); games above are what it leaves him. */
  adjustment: AdjustmentRow | null;
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
  /** A keeper's pick, logged when the draft reached his slot. */
  keeper: boolean;
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
  adp: number | null;
  /** Within the tie band of the best exact objective, along with at least one other candidate. */
  tie: boolean;
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
  /** Candidates this close to the best are a tie the model cannot separate. */
  tie_band: number;
  fallback: string | null;
  /** Why the horizon plan could not be built (mode "roster"); null otherwise. */
  roster_reason?: string | null;
  /** Mode "roster": the single roster's value with the #1 on it (no availability in it). */
  roster_objective?: number;
  timings: Record<string, number>;
  adp_source: string;
  availability_source: AvailabilitySource;
  availability_bias?: AvailabilityBias | null;
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
  /** Players on the roster: drafted, kept, and keepers still to come. */
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

/** A manual solve's settings; the ones left out (the candidate counts among them) keep their
 * session values. */
export interface SolveParams {
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
  curve?: CurveChoice;
  /** Left out: the league's table when data/ holds one that covers the draft, else a simulation. */
  survival?: SurvivalMode;
  survival_sims: number;
  survival_file?: string | null;
  solve_ahead: boolean;
  time_limit: number;
  keepers?: KeeperIn[];
  keepers_file?: string | null;
}

export interface ProjectedPlayer {
  player_id: string;
  name: string;
  team: string;
}

export interface FileEntry {
  file: string;
  kind: string;
  modified: string;
}

// ---------------------------------------------------------------- YAHOO SYNC: a draft room
export type RoomMode = "mirror" | "autopilot";
/** What the room's client was last told: armed drafts for me, mirror only follows. */
export type RoomControl = "armed" | "mirror" | "absent";

/** One client event as the fidelity log keeps it (`recv` is the API's receive time). */
export interface RoomEventEntry {
  type: "control" | "turn_start" | "draft_attempt" | "pick_landed" | "intervention" | "heartbeat" | "note";
  t?: string | number;
  recv?: string;
  src?: string;
  overall?: number;
  [key: string]: unknown;
}

export interface RoomSummary {
  attached: true;
  draft_id: string;
  session_id: string;
  slot: number;
  mode: RoomMode;
  /** The user's pre-arm of the league's draft in the dashboard (#67) that armed this room's
   * first attach; kept when the mode is switched later. */
  pre_armed?: { armed: true; at: string; by: string } | null;
  control: RoomControl;
  /** Armed: the extension clicks when the clock is down to this many seconds, unless I pick
   * first; null, at once. */
  act_at_s: number | null;
  /** The pick clock the plan budget follows, as the room reported it; null when the attach fixed the budget. */
  clock_s?: number | null;
  plan_time_limit?: number;
  price_time_limit?: number;
  num_teams: number;
  /** The room's own team count when it disagrees with the session's; arming is refused then. */
  teams_mismatch: number | null;
  rounds: number;
  players_file: string;
  attached_at: string;
  resumed: boolean;
  mapped: number;
  players: number;
  room_picks: number;
  /** The last overall up to which the session holds every room pick. */
  synced_through: number;
  /** The first overall the room has not reported while a later one is in: a gap. */
  waiting_for: number | null;
  picks_applied: number;
  next_overall: number;
  my_next_pick: number | null;
  on_the_clock: boolean;
  complete: boolean;
  /** Room message to session pick, per pick, the latest 24. */
  recent_lags: { overall: number; lag_ms: number }[];
  version: number;
  solved_version: number | null;
  fresh: boolean;
  /** Room picks with no projection, held on the board by a stand-in until pinned; and gaps, picks
   * the room never sent (a keeper the table does not know about), held by a stand-in until the
   * keeper is named. */
  standins: Standin[];
  conflicts: Record<string, unknown>[];
  unresolved: { overall: number; label: string | null; team: string | null }[];
  unmatched_yahoo: { yahoo_player_id: string; name: string; team: string; adp: number | null }[];
  unmatched_projection: { player_id: string; name: string; team: string; total: number }[];
  heartbeat: RoomEventEntry | null;
  heartbeat_age_s: number | null;
  fidelity_log: string;
  /** The user's pending "Draft in Yahoo", until the draft tab clicks it or its turn ends. */
  request: DraftRequest | null;
}

export interface DraftRequest {
  overall: number;
  board: number;
  yahoo_player_id: string;
  player_id: string | null;
  name: string;
  t: string;
  id: string; // the draft tab serves each request once by it (#22)
}

/** What the draft tab drafts from: the plan's candidates by Yahoo id. */
export interface RoomPlan {
  board: number | null;
  fresh: boolean;
  candidates: { yahoo_player_id: string; player_id: string; name: string }[];
}

export type RoomStatus = RoomSummary | { attached: false };

/** A draft room open in Chrome with the extension that no session follows yet. */
export interface SeenRoom {
  draft_id: string;
  slot: number | null;
  /** The room's own team count, once its picks have shown it. */
  room_teams: number | null;
  age_s: number;
}

export interface RoomAttachBody {
  draft_id: string;
  slot: number;
  /** The room's own team count: an attach that disagrees with the session is refused (422). */
  room_teams?: number | null;
  mode?: RoomMode;
  clock_s?: number | null;
}

export interface LagStats {
  n: number;
  p50: number | null;
  p95: number | null;
  max: number | null;
}

/** One of my picks in the scorecard: the plan's top at the turn against what landed. */
export interface FidelityRow {
  overall: number;
  round: number;
  ref_name: string | null;
  ref_kind: string | null;
  final_name: string | null;
  churn: boolean;
  actual_yid: string | null;
  actual_name: string | null;
  /** Where the actual pick stood in the candidates the drafter acted on (1 = the top). */
  actual_rank: number | null;
  label: string;
  how: string | null;
  lag_ms: number | null;
  turn_to_land_ms: number | null;
  reco_ready_ms: number | null;
  attempts: number;
}

export interface Fidelity {
  draft_id: string;
  slot: number;
  num_teams: number;
  rounds: number;
  mode: RoomMode | null;
  picks_seen: number;
  total_picks: number;
  compliance: { compliant: number; denominator: number; manual: number; my_picks_seen: number };
  counts: Record<string, number>;
  guardrails: { G2: LagStats; G2_all: LagStats; [key: string]: unknown };
  rows: FidelityRow[];
  markdown: string;
}

// The page's own origin by default: Vite proxies /api to the API, so a phone on the tailnet
// that opens the dashboard reaches the API through it. VITE_PICKANDROLL_API_BASE (a full URL)
// points the app at an API elsewhere, which must then allow this page's origin (CORS).
const BASE: string = (import.meta.env?.VITE_PICKANDROLL_API_BASE as string | undefined) || "/api";

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

/** A league folder in data/leagues/ (#67): its settings and the user's own pre-arm. */
export interface LeagueSummary {
  league: string;
  scoring: "points" | "categories";
  num_teams: number | null;
  draft_time: string | null;
  pick_seconds: number | null;
  players_file: boolean;
  survival_file: boolean;
  armed: { armed: true; at: string; by: string } | null;
}

export const api = {
  leagues: () => request<LeagueSummary[]>("/leagues"),
  /** The user's own click: arm (or disarm) a league's draft before it starts. */
  armLeague: (league: string, armed: boolean) =>
    request<LeagueSummary>(`/leagues/${encodeURIComponent(league)}/arm`, { method: "PUT", body: JSON.stringify({ armed }) }),
  projections: () => request<FileEntry[]>("/projections"),
  files: (kind: "survival" | "league" | "curve" | "adp" | "keepers") => request<FileEntry[]>(`/files?kind=${kind}`),
  /** A keepers CSV in data/, its rows as written with their line labels. */
  keepersFile: (file: string) =>
    request<{ file: string; rows: (KeeperIn & { label: string })[] }>(`/keepers-file?file=${encodeURIComponent(file)}`),
  /** A projection file's players by name, for the keeper typeahead before a session exists. */
  projectionPlayers: (file: string) => request<ProjectedPlayer[]>(`/projections/players?file=${encodeURIComponent(file)}`),
  sessions: () => request<SessionSummary[]>("/sessions"),
  session: (id: string) => request<SessionSummary>(`/sessions/${id}`),
  createSession: (body: SessionCreateBody) => request<SessionSummary>("/sessions", { method: "POST", body: JSON.stringify(body) }),
  board: (id: string, limit = 300) => request<BoardResponse>(`/sessions/${id}/board?limit=${limit}`),
  picks: (id: string) => request<PickRow[]>(`/sessions/${id}/picks`),
  addPick: (id: string, body: { team: string; player_id: string }) =>
    request<PickRow>(`/sessions/${id}/picks`, { method: "POST", body: JSON.stringify(body) }),
  /** Takes back the last real pick and the keeper picks logged behind it. */
  undoPick: (id: string) => request<PickRow & { keepers_undone: PickRow[] }>(`/sessions/${id}/picks/last`, { method: "DELETE" }),
  /** Replace the keeper table: any slot the draft has not reached (409 for one in the log). */
  setKeepers: (id: string, keepers: KeeperIn[]) =>
    request<{ keepers: KeeperRow[]; version: number }>(`/sessions/${id}/keepers`, { method: "PATCH", body: JSON.stringify({ keepers }) }),
  /** Games haircuts mid-draft: each row sets or clears its player's (`replace`: the whole
   * table). Totals are scaled, z recomputed and the plan solves again; the picks stay. */
  setAdjustments: (id: string, adjustments: AdjustmentIn[], replace = false) =>
    request<{ adjustments: AdjustmentRow[]; changed: string[]; version: number }>(`/sessions/${id}/adjustments`, {
      method: "PATCH",
      body: JSON.stringify({ adjustments, replace }),
    }),
  autopick: (id: string, body: AutoPickParams) =>
    request<{ added: PickRow[]; version: number }>(`/sessions/${id}/autopick`, { method: "POST", body: JSON.stringify(body) }),
  /** Candidates priced exactly, for every solve that starts from now on (a running one keeps
   * its own). */
  setSolveParams: (id: string, patch: { n?: number; turn_n?: number | null }) =>
    request<{ solve_params: SessionSolveParams; version: number }>(`/sessions/${id}/solve-params`, { method: "PATCH", body: JSON.stringify(patch) }),
  /** Queue a background solve; the result arrives as a `recommendation` event. */
  solve: (id: string, params: SolveParams) =>
    request<{ queued: boolean; version: number; solver: SolverStatus }>(`/sessions/${id}/solve`, { method: "POST", body: JSON.stringify(params) }),
  recommendation: (id: string) => request<RecommendationResponse>(`/sessions/${id}/recommendation`),
  teams: (id: string) => request<TeamsResponse>(`/sessions/${id}/teams`),
  score: (id: string) => request<Score>(`/sessions/${id}/score`),
  eventsUrl: (id: string) => `${BASE}/sessions/${id}/events`,
  yahooStatus: (id: string) => request<{ attached: boolean; running?: boolean; league?: string; polls?: number; last_error?: string | null }>(`/sessions/${id}/yahoo`),
  // YAHOO SYNC: the draft room open in the user's Chrome, read by the extension.
  room: (id: string) => request<RoomStatus>(`/sessions/${id}/yahoo/room`),
  attachRoom: (id: string, body: RoomAttachBody) =>
    request<RoomSummary>(`/sessions/${id}/yahoo/room`, { method: "POST", body: JSON.stringify(body) }),
  /** A field left out keeps the room's setting. */
  setRoomMode: (draftId: string, body: { mode?: RoomMode; act_at_s?: number | null }) =>
    request<RoomSummary>(`/rooms/${draftId}`, { method: "PATCH", body: JSON.stringify(body) }),
  detachRoom: (draftId: string) => request<{ attached: false; draft_id: string }>(`/rooms/${draftId}`, { method: "DELETE" }),
  pinAlias: (draftId: string, body: { yahoo_player_id: string; player_id: string }) =>
    request<{ yahoo_player_id: string; player_id: string; repaired: number[] }>(`/rooms/${draftId}/aliases`, { method: "POST", body: JSON.stringify(body) }),
  fidelity: (draftId: string) => request<Fidelity>(`/rooms/${draftId}/fidelity`),
  seenRooms: () => request<SeenRoom[]>("/rooms/seen"),
  roomPlan: (draftId: string) => request<RoomPlan>(`/rooms/${draftId}/plan`),
  /** "Draft in Yahoo": the draft tab clicks this player for my pick on the clock. */
  requestPick: (draftId: string, body: { overall: number; board: number; yahoo_player_id: string }) =>
    request<{ request: DraftRequest }>(`/rooms/${draftId}/request`, { method: "POST", body: JSON.stringify(body) }),
};

export type Standin =
  | { overall: number; yid: string; name: string; as: string; gap?: false }
  | { overall: number; yid: null; name: null; as: string; gap: true };

/** A pick the room never sent: whose it was (the team and round are known, the player is not)
 * and the stand-in holding it. */
export interface GapPick {
  overall: number;
  position: number;
  round: number;
  standin: string;
}

/** The room's gaps still held by a stand-in. */
export function gapPicks(room: RoomStatus | undefined, session: OwnerMap): GapPick[] {
  if (!room?.attached) return [];
  return room.standins
    .filter((x) => x.gap)
    .map((x) => ({ overall: x.overall, ...ownerOf(session, x.overall), standin: x.as }));
}

/** The room's stand-ins for Yahoo players the projections do not match (pinning repairs them). */
export function unmatchedStandins(room: RoomSummary): Extract<Standin, { gap?: false }>[] {
  return room.standins.filter((x): x is Extract<Standin, { gap?: false }> => !x.gap);
}

/** The marker's text for a gap. */
export function gapText(session: SessionSummary, g: GapPick): string {
  const whose = g.position === session.my_position ? "my" : teamLabel(session, g.position);
  return `unknown keeper at pick ${g.overall}, ${whose} round ${g.round}: add him to the table`;
}

export function teamLabel(session: SessionSummary, position: number): string {
  return position === session.my_position ? session.my_team : `Team ${position}`;
}

/** The overall pick of a team's round in the snake. */
export function snakeOverall(numTeams: number, position: number, round: number): number {
  return (round - 1) * numTeams + (round % 2 === 1 ? position : numTeams + 1 - position);
}

export function pickOwner(numTeams: number, overall: number): { round: number; position: number } {
  const round = Math.floor((overall - 1) / numTeams);
  const idx = (overall - 1) % numTeams;
  const position = round % 2 === 0 ? idx + 1 : numTeams - idx;
  return { round: round + 1, position };
}

/** What the owner helpers need of a session: the team count and the owner map, if any. */
export type OwnerMap = Pick<SessionSummary, "num_teams" | "pick_owners">;

/** The round and the draft position that owns `overall`: the owner map's (traded picks), else
 * the snake's. */
export function ownerOf(session: OwnerMap, overall: number): { round: number; position: number } {
  const owners = session.pick_owners;
  const round = Math.floor((overall - 1) / session.num_teams) + 1;
  if (owners && overall >= 1 && overall <= owners.length) return { round, position: owners[overall - 1] };
  return pickOwner(session.num_teams, overall);
}

/** The first pick a team holds in a round: by the owner map (null when it holds none there),
 * else the snake's. */
export function positionPick(owners: number[] | null | undefined, numTeams: number, position: number, round: number): number | null {
  if (!owners) return snakeOverall(numTeams, position, round);
  for (let k = (round - 1) * numTeams + 1; k <= round * numTeams && k <= owners.length; k++) if (owners[k - 1] === position) return k;
  return null;
}
