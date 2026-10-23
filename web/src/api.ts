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
  /** A draft of the shared archive (#77) names its league too; one pooled from the other
   * format's archive, that format and its weight. */
  seasons: { year: number; league?: string; format?: string; weight?: number; rosters: number; picks: number; scored: number; unmatched: string[] }[];
  skipped: { year: number; league?: string; format?: string; weight?: number; reason: string }[];
  check: Partial<Record<Cat, number | null>>;
  check_seasons: string[];
  /** The sum of the fitted drafts' weights (#77). */
  drafts?: number;
  /** The rosters' curve shrunk toward the simulated league by weight = D/(D+1): toward the
   * static fit until today's run lands ("static"), then toward the run ("ready"). */
  blend?: { drafts: number; weight: number; prior: string; prior_status: "static" | "ready" } | null;
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
/** A league table's blend toward the ADP formula (#77): D drafts behind it, the sum of their
 * weights (the other format's at ``weight``); D/(D+1) of each cell is the drafts'. */
export interface SurvivalBlend {
  drafts: number;
  same_format: number;
  other_format: number;
  weight: number;
}
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
  /** A league table: its blend toward the ADP formula, null for a raw table (#77). */
  blend?: SurvivalBlend | null;
  /** Beside a league table: the simulation run for the curve alone (#77). */
  curve_run?: { status: "building" | "ready" | "failed"; sims?: number; done?: number; source?: string; seconds?: number; error?: string };
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
  availability_blend?: SurvivalBlend | null;
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
  /** A league folder (#67): the fields left out come from it; a field sent, even null, wins. */
  league?: string;
  num_teams?: number;
  my_position: number;
  my_team: string;
  bench?: number;
  positions_file?: string | null;
  adp_file?: string | null;
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
  /** What a session for the league resolves to (#74); null, with the error, when its folder's
   * roster does not read. */
  resolved: LeagueResolved | null;
  error: string | null;
}

/** A league session's defaults from its folder and its format's archive (`leagues.resolved`). */
export interface LeagueResolved {
  survival: "league" | "simulate";
  /** The table under data/: the league's own, or its format's shared one. */
  survival_file: string | null;
  /** Why it simulates although its format has an archive. */
  note: string | null;
  /** The shared table's blend toward the ADP formula; null for the league's own table. */
  blend: SurvivalBlend | null;
  /** The curve the draft-day attach asks for: league once the shared table has rosters. */
  curve: CurveChoice;
  curve_drafts: number | null;
  adp_file: string | null;
  positions_file: string | null;
  rounds: number | null;
}

// ---------------------------------------------------------------- season (#92)
/** A refresh of a league's public sources: running in the background, done, failed, or refused
 * for a private league (its pages come from the extension). */
export interface SeasonRefresh {
  status: "running" | "done" | "failed" | "private";
  step: string;
  done: number;
  total: number;
  started_at: string;
  finished_at: string | null;
  error: string | null;
}

export interface SeasonTeamRef {
  team_id: number;
  name: string;
  record: string | null;
  rank: number | null;
  points_for?: number | null;
}

/** One league folder's season for the landing page's Leagues section. */
export interface SeasonSummary {
  league: string;
  name: string | null;
  scoring: "points" | "categories";
  num_teams: number;
  /** False for a private league: no public pages, the extension posts them. */
  public: boolean;
  week: number | null;
  end_week: number | null;
  my_team: SeasonTeamRef | null;
  opponent: SeasonTeamRef | null;
  has_snapshot: boolean;
  /** When the newest part of the snapshot was read. */
  updated_at: string | null;
  sources: ("public" | "extension")[];
  refresh: SeasonRefresh | null;
  error?: string;
  /** The landing grid's card (#108), once the league is read: this week's score so far, mine
   * first (categories won, or points); null before the matchup is read. */
  score?: [number, number] | null;
  /** My adds this week against the league's weekly limit; null without the week calendar. */
  adds?: Omit<MoveAdds, "weeks"> | null;
  /** The pool's flagged players by level; null, with the error, when the flags do not make. */
  flags?: Partial<Record<FlagLevel, number>> | null;
  flags_error?: string;
}

/** The landing grid's best move for a league (#108), from today's solved moves: never solved
 * by the look, only by its POST. */
export type BestMove =
  | { league: string; status: "not_solved"; system: ProjectionSystem }
  | {
      league: string;
      status: "solved";
      system: ProjectionSystem;
      /** The three weeks after this one, or the rest of this week when none follows. */
      horizon: MoveHorizon;
      label: string;
      /** The recommended move that adds most; null when none gains ``min_gain``. */
      move: BestMoveLine | null;
      /** The recommended set's size and its gain on the horizon. */
      moves: number;
      gain: number;
      min_gain: number;
    };

export interface BestMoveLine {
  add: number;
  add_name: string | null;
  /** Null: the add takes an open spot. */
  drop: number | null;
  drop_name: string | null;
  from: string;
  gain: number;
}

export interface SeasonPlayer {
  yahoo_id: number;
  name: string;
  nba_team: string | null;
  positions: string[];
  /** Yahoo's injury or availability code: O, Q, D, P, GTD, NA, INJ, SUSP... */
  status: string | null;
  status_full: string | null;
  note: string | null;
}

export interface SeasonWeek {
  number: number;
  start: string;
  end: string;
}

export interface RosterRow {
  slot: string;
  player: SeasonPlayer;
  /** Games the player's NBA team plays in the rest of this week; null without the schedule. */
  games_left: number | null;
}

export interface AvailableRow {
  player: SeasonPlayer;
  availability: "FA" | "W";
  clears: string | null;
  pct_rostered: number | null;
  pct_rostered_change: number | null;
  pct_started: number | null;
  pct_started_change: number | null;
  adds: number | null;
  drops: number | null;
  seen_at: string | null;
  games_left: number | null;
}

export interface SeasonTeam {
  team_id: number;
  name: string;
  rank: number | null;
  wins: number | null;
  losses: number | null;
  ties: number | null;
  points_for: number | null;
  waiver_priority: number | null;
  faab: number | null;
  moves: number | null;
  record: string | null;
}

export interface SeasonMatchup {
  week: number;
  teams: [number, number];
  /** Each team's week totals by Yahoo's column label (FG%, PTS...), keyed by team id. */
  totals: Record<string, Record<string, string>>;
  score: [number, number] | null;
  lines: Record<string, [number, number]>;
}

export interface SeasonTransaction {
  kind: "add" | "drop" | "trade";
  player: SeasonPlayer;
  team_id: number | null;
  team_name: string | null;
  detail: string | null;
  when: string | null;
  group: number;
}

// ---------------------------------------------------------------- week projection (#93)
/** The per-game stats a projection system gives. */
export type WeekStat = "pts" | "threes" | "reb" | "ast" | "stl" | "blk" | "tov" | "fgm" | "fga" | "ftm" | "fta";
export type Rates = Record<WeekStat, number>;
/** Basketball Monster's rest-of-season export, or Yahoo's projection for the next seven days. */
export type ProjectionSystem = "bbm" | "yahoo";
/** A solve's system: one of the two, or the blend of them the knob file may set (#152). */
export type SolveSystem = ProjectionSystem | "blend";

export interface ProjectionSystemInfo {
  label: string;
  file?: string | null;
  as_of: string | null;
  /** Players the system has a per-game line for. */
  players?: number;
}

export interface ProjectionWeek {
  number: number;
  start: string;
  end: string;
  /** The first day projected: today in the current week. */
  from: string;
  days: number;
  /** Where the week's games come from: the schedule less the out rule, or a BBM weekly export. */
  games_from: "schedule" | "bbm";
}

export interface WeekProjectionPlayer {
  /** Games per projected week: the current week from today, then the next ones. */
  games: number[];
  /** A roster's games in a starting slot per week (null for an available player). */
  started: number[] | null;
  bbm: Rates | null;
  yahoo: Rates | null;
}

export interface CategoryOddsRow {
  cat: Cat;
  /** Projected finals: the week so far plus the rest of the week. */
  mine: number | null;
  theirs: number | null;
  sd: number;
  p_win: number;
}

export interface WeekMatchupOdds {
  week: number;
  /** Mine, then the opponent. */
  teams: [number, number];
  system: ProjectionSystem;
  so_far_at: string | null;
  so_far: Record<string, Partial<Record<WeekStat | "fpts", number>>>;
  from: string;
  odds: CategoryOddsRow[];
  expected: number;
  rest: Record<string, Partial<Record<WeekStat | "fpts", number>>>;
  players_with_rates: Record<string, number>;
}

export interface WeekProjection {
  systems: Record<ProjectionSystem, ProjectionSystemInfo>;
  default: ProjectionSystem;
  phi_source: string;
  weeks: ProjectionWeek[];
  /** By Yahoo player id: my roster, this week's opponent and the available players. */
  players: Record<string, WeekProjectionPlayer>;
  matchup: WeekMatchupOdds | null;
}

// ---------------------------------------------------------------- matchup view (#116)
/** A category of my matchup: both projected finals, the week so far and the odds. */
export interface MatchupCategory extends CategoryOddsRow {
  /** The week so far, mine then theirs (a percentage's makes over attempts). */
  so_far: [number | null, number | null];
}

/** A player's line in the Matchup view: his games and starts left, his per-game rates and what
 * he adds to his team's matchup. */
export interface MatchupPlayer {
  player: number;
  slot: string;
  games: number;
  started: number;
  /** One game of his rates, the percentages and fantasy points worked out (null: no line). */
  per_game: Partial<Record<WeekStat | Cat, number | null>> | null;
  /** Expected categories he adds for his team: with him less without him from the first day. */
  cats: number;
  /** The matchup odds he adds for his team. */
  matchup: number;
}

export interface MatchupPayload {
  league: string;
  system: ProjectionSystemInfo & { key: ProjectionSystem; fallback?: string };
  week: number;
  start: string | null;
  end: string | null;
  /** The first day projected. */
  from: string;
  /** Days left, from the first day projected. */
  days: number;
  /** Mine, then the opponent. */
  teams: [number, number];
  /** Whether each team's page was read: one never read projects as an empty roster. */
  rosters_read: [boolean, boolean];
  so_far_at: string | null;
  /** Yahoo's count so far, mine first: categories won (or points). */
  score: [number, number] | null;
  tied: number | null;
  cats: MatchupCategory[];
  /** Expected categories won: the sum of the category odds. */
  expected: number;
  /** The odds of winning the matchup (independent categories, a tie half). */
  win: number;
  players: { mine: MatchupPlayer[]; theirs: MatchupPlayer[] };
}

// ---------------------------------------------------------------- season view (#116)
/** A category of a week ahead: my projected final, the opponent's (the field's average) and the
 * odds of winning it; null when no roster faced was read. */
export interface OutlookCategory {
  cat: Cat;
  mine: number | null;
  theirs: number | null;
  p_win: number | null;
}

/** A player of mine in a week ahead: his games and starts, and what he adds to the week. */
export interface OutlookPlayer {
  player: number;
  slot: string;
  games: number;
  started: number;
  cats: number;
  matchup: number;
}

export interface OutlookWeek {
  week: number;
  start: string;
  end: string;
  /** The first day projected: today's first in this week, Monday in a later one. */
  from: string;
  days: number;
  this_week: boolean;
  playoffs: boolean;
  /** The opponent the week's pairs name; null: the week is played against the field. */
  opponent: number | null;
  /** The teams averaged over when against the field. */
  field: number | null;
  /** False when no roster faced was read: the week has no odds. */
  rosters_read: boolean;
  /** Whether the NBA schedule covers every day the week counts games on. */
  scheduled: boolean;
  /** Yahoo's count so far, mine first (this week only). */
  score: [number, number] | null;
  tied: number | null;
  expected: number | null;
  win: number | null;
  games: number;
  started: number;
  cats: OutlookCategory[];
  players: OutlookPlayer[];
}

export interface OutlookSummary {
  /** The regular weeks left, this one included. */
  weeks: number;
  /** The matchup odds of the regular weeks, summed. */
  expected_wins: number;
  expected_cats: number;
  favoured: number;
  toss_up: number;
  underdog: number;
  /** Regular weeks against the field (their pairs not read). */
  field: number;
  /** Regular weeks without odds (no roster faced read). */
  unread: number;
}

export interface OutlookPayload {
  league: string;
  system: ProjectionSystemInfo & { key: ProjectionSystem; fallback?: string };
  today: string;
  team: number;
  record: string | null;
  /** Estimated from the bracket and the last week, or the first week read with no pairs. */
  first_playoff_week: number | null;
  summary: OutlookSummary;
  weeks: OutlookWeek[];
}

// ---------------------------------------------------------------- lineups (#107)
/** A slot and who is in it (null: nobody who plays can fill it). */
export interface LineupSlot {
  slot: string;
  player: number | null;
}

/** One day of a week's lineups: the recommended starters (null before the first day a change
 * counts) and bench, Yahoo's lineup as read (null: not read), the games each starts, the games
 * Yahoo's loses, whom to start and to sit, and whoever of mine plays. */
export interface LineupDay {
  date: string;
  past: boolean;
  recommended: LineupSlot[] | null;
  bench: number[] | null;
  yahoo: { read_at: string; page: string; stale: boolean; slots: { slot: string; player: number }[] } | null;
  games: { recommended: number | null; yahoo: number | null };
  lost: number | null;
  start: number[];
  sit: number[];
  playing?: number[];
}

/** A held slot and its occupant (null: open); a cleared one blocks every add. */
export interface HeldSlot {
  slot: string;
  player: number | null;
  cleared: boolean;
}

export type LineupAlert =
  | ({ kind: "cleared" } & ClearedPlayer)
  | { kind: "unknown_status"; player: number; status: string }
  | { kind: "held_lower_bound"; slots: Record<string, number> }
  | { kind: "rule_unknown" };

export interface LineupPayload {
  week: number;
  /** The weeks the route answers: this one and the moves' three after it. */
  weeks?: number[];
  start: string;
  end: string;
  /** The first day a change counts. */
  first: string;
  this_week: boolean;
  system: ProjectionSystemInfo & { key: ProjectionSystem; fallback?: string };
  rule: { changes: "daily" | "weekly" | null; from: "today" | "tomorrow" | null; deadline: string | null; source: string | null };
  slots: string[];
  held: {
    slots: HeldSlot[];
    /** Open slots by kind, every kind the league has (0: full). */
    open: Record<string, number>;
    /** My active players eligible for a kind the league has, a full one included. */
    eligible: { player: number; slots: string[] }[];
    source: string;
    lower_bound: boolean;
  };
  alerts: LineupAlert[];
  days: LineupDay[];
  summary: { lost: number; differ: string[]; unread: string[] };
  /** A private league's pages for the user's Chrome to open. */
  needs: string[];
  players: Record<string, { name: string; nba_team: string | null; positions: string[]; status: string | null }>;
}

// ---------------------------------------------------------------- moves (#94)
/** The moves' horizons: the rest of this week against the opponent, and the three weeks after
 * it against the field. */
export type MoveHorizon = "week" | "three";
/** The horizons the scorecard values a move on: the solve's two and the rest of the season (#144). */
export type JudgedHorizon = MoveHorizon | "season";

/** A move's rest of the season (#151): the decision log's own figure for it (#144), from its day
 * to the season's last day, playoffs included, in the scorer's units (category z or points, net
 * of an empty line): the add's games less the drop's, each at his per-game value, with how many
 * are extrapolated past the schedule read. Shown beside the horizons; nothing ranks on it. Kept
 * apart from ``MoveHorizon``: it is not expected categories. Its value null when the add or the
 * drop has no line. */
export interface MoveRos {
  value: number | null;
  add_games: number;
  /** Null: no drop (an open spot). */
  drop_games: number | null;
  extrapolated: { add: number; drop: number | null };
  from: string;
  to: string;
}

/** A set's rest of the season: the sum of its moves'. */
export interface RosTotal {
  value: number;
}

/** An add, the player dropped for him (null: an open spot) and the day he plays from (a waiver
 * claim's clear date). */
export interface MoveRef {
  add: number;
  drop: number | null;
  from: string;
}

/** A candidate's best single move on a horizon, and what the next best drop costs. */
export interface CandidateGain {
  /** Expected categories won over the horizon (a points league: matchups won). */
  gain: number;
  drop: number | null;
  /** With no drop and no open spot: the held-slot move that makes room for him (#124). */
  held?: HeldMove | null;
  next_drop: number | null;
  next_price: number | null;
  /** This move to the season's end (#151). */
  ros?: MoveRos | null;
}

export interface MoveCandidate {
  from: string;
  /** Null when no move with him fits (no adds left, no drop). */
  week: CandidateGain | null;
  three: CandidateGain | null;
  /** Why no move fits on either horizon, in words. */
  reason?: string;
}

export interface RecommendedMove extends MoveRef {
  /** With no drop and no open spot: the held-slot move that makes room for him (#124). */
  held?: HeldMove | null;
  /** What the move adds to its set on each horizon. */
  marginal: Record<MoveHorizon, number>;
  ros?: MoveRos | null;
  /** The set less the re-solve without this add, and with this drop kept (null: no drop). */
  price_without: number;
  price_keep: number | null;
  instead_without: HeldRef[];
  instead_keep: HeldRef[] | null;
}

/** A move of a re-solve's set, naming the held-slot move an add without a drop needs (#124). */
export interface HeldRef extends MoveRef {
  held?: HeldMove | null;
}

export interface HeldMove {
  player: number;
  slot: string;
}

/** A player moved to a held slot who comes back inside a horizon, and whom the return sends:
 * the least valuable active player then, maybe the player himself (#97). */
export interface Comeback {
  player: number;
  slot: string;
  from: string;
  drop: number;
}

export interface RecommendedSet {
  moves: RecommendedMove[];
  gain: Record<MoveHorizon, number>;
  /** Players the set moves to an IL or NA slot to open a spot. */
  held: HeldMove[];
  /** By horizon, the drops their returns force. */
  comebacks?: Partial<Record<MoveHorizon, Comeback[]>>;
  ros?: RosTotal | null;
}

/** A streamer valued to the season's end as kept there: the later step that drops him (#151). */
export interface DroppedBy {
  add: number;
  from: string;
}

/** A streaming plan's step (#136): a dated move turning a stream spot over, its drop the spot's
 * holder before (the occupant, or an earlier step's add). */
export interface PlanStep extends MoveRef {
  /** The occupant whose spot the step turns over. */
  spot: number;
  /** The step's own gain on each horizon: the plan up to it less the plan before it. */
  marginal: Record<MoveHorizon, number>;
  /** The log's figure for the step, its add kept to the season's end; a later step that drops
   * him says which, and the plan's total telescopes over the two. */
  ros?: MoveRos | null;
  dropped_by?: DroppedBy | null;
}

/** The week's streaming plan (#136) against its recommended set. */
export interface StreamPlan {
  /** The set's moves the plan keeps (those that do not drop a stream spot's occupant). */
  base: (MoveRef & { held?: HeldMove | null; marginal: Record<MoveHorizon, number>; ros?: MoveRos | null; dropped_by?: DroppedBy | null })[];
  /** By day. */
  steps: PlanStep[];
  spots: { player: number; steps: number }[];
  /** My started games over the rest of the week with no move, the set and the plan. */
  games: { none: number; set: number; plan: number };
  held: HeldMove[];
  comebacks: Partial<Record<MoveHorizon, Comeback[]>>;
  adds: { set: number; plan: number };
  /** Expected categories won on each horizon with no move, the set and the plan. */
  value: Record<"none" | "set" | "plan", Record<MoveHorizon, number>>;
  /** The plan less the set, on each horizon. */
  gain: Record<MoveHorizon, number>;
  /** The set's and the plan's rest of the season: the sums of their moves'. */
  ros?: { set: RosTotal | null; plan: RosTotal | null };
  /** Its week beats the set's by more than the floor; else by how much it falls short. */
  recommended: boolean;
  short: number | null;
  floor: number;
  /** Why it is not recommended: under the floor, or the plan with the best week would clear it
   * but costs the three weeks after, which the planner never trades (``guard``). */
  reason: "short" | "guard" | null;
  guard: PlanGuard | null;
}

/** The plan the three-week guard refused (#136): what it would buy, for the user to weigh. */
export interface PlanGuard {
  steps: (MoveRef & { spot: number })[];
  spots: number[];
  /** My started games over the rest of the week with it. */
  games: number;
  /** Its gain on the set on each horizon (the three weeks' negative). */
  gain: Record<MoveHorizon, number>;
  /** Its moves' rest of the season less the set's. */
  ros?: RosTotal | null;
}

export interface MoveHorizonInfo {
  label: string;
  weeks: number[];
  from: string | null;
  opponent: number | null;
  /** My roster's expected categories over the horizon without a move. */
  base: number;
}

export interface MoveAdds {
  /** The league's weekly limit (null: none). */
  limit: number | null;
  /** My adds this week on the transactions page; a floor when the page may not reach back. */
  used: number;
  complete: boolean;
  left: number | null;
  weeks: { start: string; end: string; adds: number | null }[];
}

/** A held player whose status cleared: Yahoo refuses every add until he is activated, which
 * drops ``drop`` (maybe himself) on ``from`` (#124). */
export interface ClearedPlayer {
  player: number;
  slot: string;
  status: string | null;
  from: string;
  drop: number | null;
}

/** One of my active players under the keep rule (#124): his rest-of-season per-game value, when
 * he is back, and its three tests. Protected: all three, never dropped; bench: better than the
 * best add and back within a week, not dropped either. */
export interface KeptPlayer {
  player: number;
  value: number | null;
  back: string | null;
  net_positive: boolean;
  beats_best: boolean;
  returns: boolean;
  protected: boolean;
  bench: boolean;
}

export interface KeepRule {
  /** What a player's value must beat the best add's by. */
  floor: number;
  /** The pool's average per-game value (0 for category sums). */
  average?: number;
  best: { player: number; value: number } | null;
  players: KeptPlayer[];
}

/** What to do with one of my players who is out (#124): stash him in an open held slot, say who
 * leaves a full one, keep him on the bench, or nothing (droppable). */
export type StashAdvice = "stash" | "il_full" | "bench" | "droppable";

export interface Stash {
  player: number;
  status: string | null;
  back: string | null;
  /** The held slots his status allows, and the one open for him (null: none). */
  slots: string[];
  slot: string | null;
  protected: boolean;
  bench: boolean;
  /** His per-game value above an empty line times his games from his return; null without a line. */
  net: number | null;
  advice: StashAdvice;
  /** A full slot's occupant who should leave it: activated (dropping ``drop``) or dropped. */
  leave: { player: number; slot: string; how: "activate" | "drop"; drop: number | null; net: number | null; protected: boolean } | null;
  /** A stash: the best add for the spot it frees, by horizon. */
  add: Record<MoveHorizon, { player: number; gain: number; ros?: MoveRos | null } | null> | null;
}

export interface MovesPayload {
  system: ProjectionSystemInfo & { key: ProjectionSystem; fallback?: string };
  cleared?: ClearedPlayer[];
  keep_rule?: KeepRule;
  stash?: Stash[];
  horizons: Record<MoveHorizon, MoveHorizonInfo>;
  adds: MoveAdds;
  /** By Yahoo player id. */
  candidates: Record<string, MoveCandidate>;
  recommended: Record<MoveHorizon, RecommendedSet>;
  /** The week's streaming plan (#136); null without a stream spot. */
  plan?: StreamPlan | null;
  /** Available players without a line in the system (no move valued). */
  unprojected: number;
  search: { pool: number; min_gain: number };
}

/** A category over a horizon: expected wins summed over its weeks; this week's finals too. */
export interface MoveCategory {
  wins: number;
  mine?: number | null;
  theirs?: number | null;
}

export interface MoveDetail extends MoveRef {
  held: HeldMove[];
  horizons: Record<
    MoveHorizon,
    {
      before: number;
      after: number;
      /** After less before, unrounded: the drop list's figure. */
      gain: number;
      cats: { before: Partial<Record<Cat, MoveCategory>>; after: Partial<Record<Cat, MoveCategory>> };
      comebacks?: Comeback[];
    }
  >;
  /** The move to the season's end, beside its two horizons (#151). */
  ros?: MoveRos | null;
  /** Every drop the add can come with, best over three weeks first; ``kept``: the keep rule keeps
   * him, so the search never takes it (#124). */
  drops: ({ drop: number | null; kept?: boolean; held?: HeldMove | null; ros?: MoveRos | null } & Record<MoveHorizon, number>)[];
  /** The best other adds for this drop. */
  adds: ({ add: number; ros?: MoveRos | null } & Record<MoveHorizon, number>)[];
}

// ---------------------------------------------------------------- strategy (#110)
/** The frontier's weights of this week against the rest of the season. */
export type StrategyWeightKey = "week" | "even" | "natural" | "season";
/** Which solver's set a point recommends. */
export type StrategySource = "search" | "milp" | "both";
/** HiGHS's own word: solved to the gap, stopped at the time limit with a set, or no set. */
export type MilpStatus = "optimal" | "time_limited" | "failed";

/** A set's exact gains: this week, the three weeks after it, the season pace (the three weeks'
 * average week times the weeks left, in category-weeks; the ROS column is the schedule-based
 * figure, #151) and the weight's own value. */
export interface StrategyGain {
  week: number;
  three: number;
  season: number;
  weighted: number;
}

/** One solver's set at a weight. */
export interface StrategyBlock {
  seconds: number;
  moves: MoveRef[];
  gain: StrategyGain;
  /** The search's: seconds spent pricing its set by re-solves. */
  pricing?: number;
}

export interface MilpBlock extends Partial<StrategyBlock> {
  status: MilpStatus | "pending";
  size?: { variables: number; binaries: number; constraints: number };
  /** The program's own value of its set on the horizons it modelled. */
  model?: Partial<Record<"week" | "later", number>>;
}

/** A move of a point's recommended set, priced by re-solves once ``priced``. */
export interface StrategyMove extends MoveRef {
  priced: boolean;
  held?: HeldMove | null;
  marginal?: Record<MoveHorizon | "weighted", number>;
  ros?: MoveRos | null;
  price_without?: number;
  price_keep?: number | null;
  instead_without?: HeldRef[];
  instead_keep?: HeldRef[] | null;
}

export interface StrategyPoint {
  key: StrategyWeightKey;
  label: string;
  lambda: number;
  natural: boolean;
  /** The weight the knob file recommends (#152): marked, never executed. */
  recommended?: boolean;
  /** waiting → searched (the search's set) → priced → done (the program in). */
  stage: "waiting" | "searched" | "priced" | "done";
  source?: StrategySource;
  /** How the shown set came about when it is not simply one solver's. */
  note?: string | null;
  /** The shown set's weighted value less the other solver's (null: the same set). */
  ahead?: number | null;
  moves?: StrategyMove[];
  /** The held-slot moves the set's adds without a drop need. */
  held?: HeldMove[];
  gain?: StrategyGain;
  /** The set's rest of the season, the sum of its moves' (#151). */
  ros?: RosTotal | null;
  cats?: Record<MoveHorizon, { before: Partial<Record<Cat, MoveCategory>>; after: Partial<Record<Cat, MoveCategory>> }>;
  search?: StrategyBlock;
  milp?: MilpBlock | null;
  /** At a program's solution: each pool player's and each of mine's first-order value. */
  first_order?: Record<string, number>;
}

export interface StrategySettings {
  pool: number;
  weights: StrategyWeightKey[];
  keep: number[];
  program_only: boolean;
}

export interface StrategyPayload {
  league: string;
  status: "not_solved" | "solving" | "solved" | "failed" | "cancelled";
  system: ProjectionSystemInfo & { key: SolveSystem; fallback?: string; blend?: number };
  step?: string | null;
  error?: string | null;
  weeks_left?: number;
  settings?: StrategySettings;
  /** The knob file's horizon weight (#152), natural by default. */
  recommended?: StrategyWeightKey | null;
  keep_rule?: KeepRule;
  pool?: number[];
  horizons?: Record<MoveHorizon, MoveHorizonInfo> & { season: { label: string; title?: string; weeks_left: number; base: number | null } };
  adds?: MoveAdds;
  points?: StrategyPoint[];
  time_limit?: number;
  min_gain?: number;
  started_at?: string;
  finished_at?: string | null;
  timing?: Partial<Record<"moves" | "first" | "done", number>>;
}

export interface StrategyOptions {
  lock?: number[];
  program_only?: boolean;
  pool?: number;
}

// ---------------------------------------------------------------- trades (#96)
/** A proposal between my roster and one other team's, by Yahoo player id. */
export interface TradeBody {
  team: number;
  give: number[];
  get: number[];
  system?: ProjectionSystem;
  /** The day it takes effect; by default when Yahoo would process it if accepted today. */
  effective?: string | null;
}

export interface TradePlayerRef {
  player: number;
  name: string;
  nba_team: string | null;
  positions: string[];
  status: string | null;
}

/** A category's expected wins over a horizon, before and after the trade. */
export interface TradeCategory {
  cat: Cat;
  before: number;
  after: number;
  change: number;
}

export interface TradeSide {
  team: number;
  name: string;
  /** This week's named opponent. */
  opponent: number | null;
  opponent_name: string | null;
  /** False when the side's matchup page was not read: its week starts from nothing so far. */
  so_far_read: boolean;
  horizons: Record<MoveHorizon, { before: number; after: number; change: number; cats: TradeCategory[] }>;
  /** Its roster's rest of the season from the trade's day (#151): the change is what it
   * receives less what it sends and drops; ``unvalued``: players with no line, counted as
   * nothing. Null without the league's scorer. */
  ros?: { before: number; after: number; change: number; from: string; unvalued: number } | null;
  roster: {
    spots: number;
    /** Active players after the trade and its held-slot moves, before any drop. */
    active: number;
    open: number;
    /** False when the side must drop someone: the trade as entered is not valid in Yahoo. */
    valid: boolean;
    held_moves: HeldMove[];
    /** The players it misses least, chosen by the evaluator. */
    drops: TradePlayerRef[];
  };
}

export interface TradeGames {
  games: number;
  started: number;
}

/** A player's rest of the season from a day (#151): his per-game value times his games to the
 * season's last day, as the decision log counts a move's. */
export interface PlayerRos {
  value: number;
  per_game: number;
  games: number;
  extrapolated: number;
}

export interface TradePlayer extends TradePlayerRef {
  from: number;
  to: number;
  /** On his old team as if no trade, and with it on his old team (until the date) and new one. */
  games: Record<MoveHorizon, { before: TradeGames; old: TradeGames; new: TradeGames }>;
  /** From the trade's day. */
  ros?: PlayerRos | null;
}

export type MarginReading = "crosses" | "wins_at_zero" | "loses_at_max";

export interface TradeMargin {
  horizon: MoveHorizon;
  /** The share of what I receive's projection that leaves my change at zero. */
  neutral: number | null;
  reading: MarginReading;
  /** My change at the full projection. */
  change: number;
  max: number;
}

export interface TradePayload {
  trade: { team: number; give: number[]; get: number[] };
  effective: string;
  /** "review": accepted today and processed after the league's review; "requested": the body's. */
  effective_rule: "review" | "requested";
  review_days: number;
  first_day: string;
  system: ProjectionSystemInfo & { key: ProjectionSystem; fallback?: string };
  horizons: Record<MoveHorizon, { label: string; weeks: number[]; from: string | null }>;
  /** The horizon the drops, the fill and the margin are taken on. */
  lead: MoveHorizon;
  sides: { mine: TradeSide; theirs: TradeSide };
  players: TradePlayer[];
  margin: TradeMargin | null;
  /** The best free agent for a spot the trade frees on my side, valued beside the trade. */
  fill: (TradePlayerRef & { from: string; gain: Record<MoveHorizon, number>; ros?: PlayerRos | null }) | null;
}

/** A recorded week's result for one team (#97): categories won, lost and tied, or a points
 * league's points and the opponent's. */
export interface WeekResult {
  won?: number;
  lost?: number;
  tied?: number;
  points?: number;
  against?: number;
  outcome: "W" | "L" | "T";
}

/** A recorded week, as the season's history lists it. */
export interface RecordedWeek {
  week: number;
  start: string;
  end: string;
  recorded_at: string | null;
  /** When a later record of the week changed it (a stat correction). */
  revised_at: string | null;
  opponent: number | null;
  opponent_name: string | null;
  result: WeekResult | null;
  games: { played: number; scheduled: number } | null;
  /** My place and record in the standings as of the week's end. */
  rank: number | null;
  record: string | null;
  standings_through: string | null;
  players: number;
  /** What the record lacks: drafted players without a line, teams without a page. */
  missing: Record<string, number | string>;
}

export interface SeasonWeeks {
  league: string;
  my_team_id: number | null;
  weeks: RecordedWeek[];
}

/** How a move made compares with the solve logged before it (#125). */
export type MatchKind = "as_recommended" | "differently" | "not_recommended" | "no_entry";
/** A move's group on the scorecard (#126): projected by its own entry and realized, realized
 * only (no projection of its own, or a borrowed scorer), or neither. */
export type MoveGroup = "scored" | "realized_only" | "unscored";
export type UnscoredReason = "no_time" | "no_scorer" | "not_read" | "unmatched";

/** A move's projection as its entry logged it, in the scorer's units, on each horizon. */
export interface LoggedSpan {
  from: string;
  to: string;
  add_games: number;
  drop_games: number | null;
  value: number | null;
  /** The value by category (a points league's by scoring stat); entries logged before #129 have none. */
  cats?: Record<string, number> | null;
  /** The season's games past the schedule read, at the team's rate (#144): the season horizon only. */
  extrapolated_games?: { add: number; drop: number | null };
}

/** A move's realized span: its games from the move on, through the last day read. */
export interface RealizedSpan {
  from: string;
  to: string;
  through: string | null;
  complete: boolean;
  /** The days over but not read yet. */
  missing: string[];
  add_games: number | null;
  drop_games: number | null;
  add: number | null;
  drop: number | null;
  /** The games of a player not matched to the box scores. */
  gaps: number;
  value: number | null;
  /** The value by category (a points league's by scoring stat); null while a side is unmatched. */
  cats?: Record<string, number> | null;
}

export interface RealizedSide {
  yahoo: number;
  espn: string | null;
  by: "id" | "team" | "name" | null;
}

export interface Realized {
  valued: boolean;
  reason: UnscoredReason | null;
  add: RealizedSide | null;
  drop: RealizedSide | null;
  horizons: Partial<Record<JudgedHorizon, RealizedSpan>>;
  /** The entry whose scorer valued it; ``own`` false for a borrowed one. */
  scorer: { entry: string; own: boolean } | null;
  /** The days from the matched entry's first day to the move's. */
  lag_days: number | null;
}

export interface ScorecardMove {
  group: MoveGroup;
  day: string | null;
  at: string | null;
  add: number | null;
  drop: number | null;
  detail: string | null;
  bid: number | null;
  match: { kind: MatchKind; entry: string | null; move: { add: number; drop: number | null } | null; near: boolean };
  projected: {
    set: string;
    gain: Partial<Record<MoveHorizon, number | null>>;
    value: { add: number | null; drop: number | null; horizons: Partial<Record<JudgedHorizon, LoggedSpan>> };
    /** The set's odds of winning the matchup and its expected categories, before and after it (#129). */
    odds?: Record<"before" | "after", { matchup: number | null; expected: number | null } | null>;
    /** Whether the decision log flagged it as costing the season (#144); null before the flag. */
    season_costly?: boolean | null;
  } | null;
  realized: Realized | null;
  /** The horizon it is judged on: the one its set was recommended for (#143, the season #144). */
  judged?: JudgedHorizon;
  /** Projected positive on its judging horizon and below minus the protection floor over the
   * season (#144); null for a move with no flag logged. */
  season_costly?: boolean | null;
  /** The knobs in force at the entry it matched (#129). */
  knobs?: Partial<Record<KnobName, unknown>> | null;
}

export interface ScorecardCat {
  cat: string;
  p_win: number | null;
  projected: { mine: number | null; theirs: number | null } | null;
  actual: { mine: number | null; theirs: number | null } | null;
  won: number | null;
}

/** A recorded week against the decision log's projection of it (#126). */
export interface ScorecardWeek {
  week: number;
  start: string;
  end: string;
  scoring: "categories" | "points" | null;
  projected: { entry: string; at: string; source: string | null; expected: number | null; matchup: number | null } | null;
  actual: { opponent: number; result: WeekResult; won: number; categories: number | null } | null;
  cats: ScorecardCat[];
  standing: { rank: number | null; record: string | null; teams: number } | null;
  moves: ScorecardMove[];
}

export interface MovesCompared {
  moves: number;
  projected: number;
  realized: number;
  /** How many realized in the projected direction. */
  same_way: number;
  /** The realized sum over the projected; null when the projected is not positive. */
  share: number | null;
  /** How many were judged on each horizon: the one each move's set was recommended for (#143). */
  horizons?: Partial<Record<JudgedHorizon, number>>;
}

/** Moves counted against the season (#144), with how many of the scored realized below zero so far. */
export interface SeasonCount {
  moves: number;
  below_so_far: number;
  /** The moves the decision log flagged or cleared (``season_costly`` only). */
  checked?: number;
}

export interface MovesSummary {
  made: number;
  as_recommended: number;
  differently: number;
  not_recommended: number;
  no_entry: number;
  near: number;
  projected: number;
  projected_value: Partial<Record<JudgedHorizon, number>>;
  scored: number;
  realized_only: number;
  unscored: number;
  realized_value: Partial<Record<JudgedHorizon, number>>;
  complete: Partial<Record<JudgedHorizon, number>>;
  /** The scored moves whose judging horizon is over, each on it (#143); null for none. */
  compared: MovesCompared | null;
  /** The moves projected below zero over the season and the flagged season-costly (#144). */
  season_negative?: SeasonCount;
  season_costly?: SeasonCount;
  unscored_by: Partial<Record<UnscoredReason, number>>;
  gaps: number;
}

export interface ScorecardToDate {
  weeks: number;
  projected: number;
  record: string;
  expected_wins: number | null;
  wins: number;
  expected_categories: number | null;
  categories: number | null;
  standing: ScorecardWeek["standing"];
  moves: MovesSummary;
}

export interface CalibrationBucket {
  from: number;
  to: number;
  count: number;
  odds: number | null;
  won: number | null;
}

export interface ScorecardPayload {
  league: string;
  public: boolean;
  system: string;
  status: "recorded" | "not_recorded" | "no_team";
  week: number | null;
  card: ScorecardWeek | null;
  weeks: ScorecardWeek[];
  to_date?: ScorecardToDate;
  calibration?: { weeks: number; brier: number | null };
  /** The names of the players the moves name, by Yahoo id. */
  players?: Record<string, string>;
}

// ---------------------------------------------------------------- the Progress view (#129)
/** The knobs of docs/AUTOPILOT.md section 6, as the decision log records them. */
export type KnobName =
  | "system"
  | "blend"
  | "horizon_weight"
  | "protection_floor"
  | "plan_floor_cats"
  | "plan_floor_points"
  | "stash_threshold"
  | "faab_sizing"
  | "daily_cap";
export type Scoring = "categories" | "points";

/** Wins and categories summed over some weeks: the wins and the matchup odds over the projected
 * weeks, every win, and the categories over the weeks with both. */
export interface ProgressRunning {
  weeks: number;
  expected: number;
  won: number;
  won_all: number;
  expected_categories: number | null;
  categories: number | null;
}

/** A league's week on the Progress view, with its running sums to it. */
export interface ProgressWeek {
  week: number;
  start: string;
  end: string;
  scoring: Scoring | null;
  /** The odds of winning the matchup, on a week with a result. */
  expected: number | null;
  won: number | null;
  outcome: "W" | "L" | "T" | null;
  expected_categories: number | null;
  categories: number | null;
  brier: number | null;
  rank: number | null;
  teams: number | null;
  record: string | null;
  moves: {
    made: number;
    scored: number;
    realized_only: number;
    unscored: number;
    /** On the week, in the league's scorer's units. */
    projected: number | null;
    realized: number | null;
    compared: MovesCompared | null;
    paid: number;
  };
  /** Not recorded yet: counted once the lineup log exists. */
  lineup_lost: number | null;
  cum: ProgressRunning & {
    moves: { made: number; realized_value: Partial<Record<MoveHorizon, number>>; compared: MovesCompared | null };
  };
}

/** A scoring's moves pooled: never summed with the other scoring's, whose units differ. */
export interface ScoringMoves {
  made: number;
  realized: number | null;
  compared: MovesCompared | null;
}

export interface PooledWeek extends ProgressRunning {
  week: number;
  leagues: number;
  brier: number | null;
  buckets: CalibrationBucket[];
  record: string;
  moves: Partial<Record<Scoring, ScoringMoves>>;
  cum: ProgressRunning & { moves: Partial<Record<Scoring, ScoringMoves>> };
}

export interface ProgressLeague {
  league: string;
  public: boolean;
  status: ScorecardPayload["status"];
  scoring: Scoring | null;
  weeks: ProgressWeek[];
  to_date?: ScorecardToDate;
}

export interface ProgressMove extends ScorecardMove {
  league: string;
  public: boolean;
  week: number;
  scoring: Scoring | null;
  names: { add: string | null; drop: string | null };
}

/** One half of a knob change over the weeks it is judged on. */
export interface AbHalf {
  leagues: string[];
  wins_above: number | null;
  moves_a_week: number | null;
  standing_climbed: number;
  brier: number | null;
  moves: Partial<Record<Scoring, { moves: number; projected: number; realized: number; share: number | null }>>;
}

export interface KnobChange {
  id: string;
  monday: string;
  knob: KnobName;
  from: unknown;
  to: unknown;
  /** The leagues that took it: the A half. */
  leagues: string[];
  source: "master" | "user" | null;
  reason: string | null;
  decided_at: string | null;
  verdict: "kept" | "reverted" | null;
  judged_on: string | null;
  rolled_out: string | null;
  week: number | null;
  ab: {
    window: [number, number] | null;
    a: AbHalf;
    b: AbHalf;
    /** Each week's wins above expected a league, both halves, from two weeks before it. */
    series: { week: number; a: number | null; b: number | null }[];
  } | null;
}

export interface ProgressNote {
  monday: string;
  posted: string | null;
  working: string | null;
  not_working: string | null;
  decision: string | null;
  actions: string[];
  week: number | null;
  /** The week the note looks back on. */
  scored_week: number | null;
}

export interface ProgressSentence {
  topic: "wins" | "league" | "moves" | "odds" | "knobs";
  /** "pooled" or a league's id. */
  scope: string;
  tone: "good" | "bad" | "neutral";
  text: string;
}

export interface ProgressPayload {
  system: string;
  today: string;
  week: number | null;
  last_recorded: number | null;
  weeks: { week: number; start: string; end: string }[];
  leagues: ProgressLeague[];
  pooled: { weeks: PooledWeek[]; to_date: PooledWeek["cum"] | null; calibration: { weeks: number; brier: number | null; buckets: CalibrationBucket[] } };
  moves: ProgressMove[];
  knobs: {
    in_force: Partial<Record<KnobName, unknown>>;
    leagues: Record<string, Partial<Record<KnobName, unknown>>>;
    frozen: Record<string, KnobName[]>;
    changes: KnobChange[];
  };
  notes: ProgressNote[];
  action_items: { monday: string; items: string[] } | null;
  sentences: ProgressSentence[];
  sources: {
    leagues: number;
    recorded: number;
    public: number;
    moves: Record<"made" | "as_recommended" | "differently" | "not_recommended" | "no_entry" | "near", number>;
    knob_file: boolean;
    notes: number;
  };
  problems: string[];
  skipped: { league: string; reason: string }[];
}

/** The season view: the summary plus the week, standings, rosters, matchup and the pool. */
export interface SeasonView extends SeasonSummary {
  settings: {
    cats: Cat[];
    points: Record<string, number> | null;
    max_weekly_adds: number | null;
    waiver_rule: string | null;
    uses_faab: boolean | null;
    end_date: string | null;
  };
  today: string;
  current_week: SeasonWeek | null;
  weeks_ahead: SeasonWeek[];
  calendar_estimated: boolean | null;
  teams: SeasonTeam[];
  roster: RosterRow[];
  rosters: Record<string, RosterRow[]>;
  matchups: SeasonMatchup[];
  matchup: SeasonMatchup | null;
  available: AvailableRow[];
  transactions: SeasonTransaction[];
  fetched: Record<string, { at: string; source: "public" | "extension" }>;
  schedule: { days: number; first: string | null; last: string | null };
  week_projection: WeekProjection;
  /** The breakout flag (#95) of every available player a signal speaks for, by Yahoo id. */
  flags?: Record<string, PlayerFlag>;
  flag_inputs?: FlagInputs;
  /** The flag's own thresholds, for the explainer (#113). */
  flag_config?: FlagConfig;
}

// ---------------------------------------------------------------- breakout flag (#95)
export type FlagLevel = "watch" | "add" | "must-add";
export type FlagSignalKey = "surge" | "minutes" | "value" | "opportunity";
export interface FlagSignal {
  /** 0 to 1. */
  score: number;
  /** The evidence with every number; null when the signal says nothing. */
  reason: string | null;
  facts: Record<string, unknown>;
}
export interface PlayerFlag {
  /** From the sum of the four scores; null under watch. */
  level: FlagLevel | null;
  score: number;
  signals: Record<FlagSignalKey, FlagSignal>;
}
export interface FlagInputs {
  buzz?: { today: string | null; rows: number; earlier_days: number; same_hour?: number };
  injuries?: { read_at: string | null; players: number };
  /** The rest-of-season export the minutes, value and opportunity read. */
  projection?: string | null;
  past_days?: Record<string, { file: string; as_of: string; stale?: boolean } | null>;
  /** The signals today's inputs cannot score for anyone, each with why. */
  silent?: Partial<Record<FlagSignalKey, string>>;
  /** The flags could not be made. */
  error?: string;
}
/** ``season/flags.py``'s constants, as the season view sends them. */
export interface FlagConfig {
  /** Highest first. */
  levels: { level: FlagLevel; floor: number }[];
  /** The most the four scores add up to. */
  max: number;
  opportunity_needs_another: boolean;
  past_days_max_days: number;
  signals: {
    surge: { name: string; jump_full: number; jump_floor: number; history_days: number; adds_full: number; adds_floor: number; buzz_rows: number; buzz_last: number };
    minutes: { name: string; minutes_full: number; usage_full: number; usage_weight: number; min_games: Record<string, number> };
    value: { name: string; rank: number; pct: number; rank_scale: number };
    opportunity: { name: string; out_days: number; full: number; unknown_mpg: number };
  };
}

/** The strategy run's query: the system, the locks, the program alone and the pool. */
export function strategyQuery(system: ProjectionSystem, o: StrategyOptions): string {
  const q = new URLSearchParams({ system });
  for (const id of o.lock ?? []) q.append("lock", String(id));
  if (o.program_only) q.set("program_only", "true");
  if (o.pool) q.set("pool", String(o.pool));
  return q.toString();
}

// ---------------------------------------------------------------- the freshness light (#153)
/** Red: failed, or missing once the routine's run is due; amber: stale or not due yet. */
export type StatusState = "green" | "amber" | "red";

/** One row of the light's sheet: what it is, its time, its state (none: on request) and why. */
export interface StatusRow {
  kind: string;
  state: StatusState | null;
  reason: string;
}

export interface RoutineRow extends StatusRow {
  started_at: string | null;
  finished_at: string | null;
  steps: Record<string, { status: "ok" | "failed" | "skipped" | null; detail: string | null }>;
}

export interface ExportRow extends StatusRow {
  label: string;
  file: string | null;
  as_of: string | null;
}

/** A public league's last refresh, or one of the private league's pages. */
export interface YahooRow extends StatusRow {
  read_at: string | null;
  /** The last refresh job: the service's own, or after a restart the last its log has (logged). */
  status?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  step?: string | null;
  done?: number | null;
  total?: number | null;
  error?: string | null;
  warnings?: Record<string, string>;
  logged?: boolean;
  snapshot_at?: string | null;
}

export interface BuiltRow extends StatusRow {
  built_at: string | null;
  system?: string | null;
  projection_file?: string | null;
  inputs?: Record<string, string | null>;
}

export interface StatusSection<R extends StatusRow> {
  state: StatusState;
  rows: R[];
}

/** A league; one whose settings do not read carries only its error. */
export interface StatusLeague {
  league: string;
  name?: string | null;
  public?: boolean;
  state: StatusState;
  error?: string;
  yahoo?: StatusSection<YahooRow>;
  recommendations?: StatusSection<BuiltRow> & { inputs: Record<string, string | null> };
}

export interface StatusPayload {
  generated_at: string;
  today: string;
  due_at: string;
  state: StatusState;
  routine: RoutineRow;
  exports: StatusSection<ExportRow>;
  leagues: StatusLeague[];
}

export const api = {
  /** Every league folder's season (#92), for the landing page. */
  seasons: () => request<SeasonSummary[]>("/seasons"),
  season: (league: string) => request<SeasonView>(`/seasons/${encodeURIComponent(league)}`),
  /** Every available player's best move on both horizons and the recommended sets (#94). */
  moves: (league: string, system: ProjectionSystem) =>
    request<MovesPayload>(`/seasons/${encodeURIComponent(league)}/moves?system=${system}`),
  /** My matchup this week as a scoreboard, and what each player adds to it (#116). */
  matchup: (league: string, system: ProjectionSystem) =>
    request<MatchupPayload>(`/seasons/${encodeURIComponent(league)}/matchup?system=${system}`),
  /** A week's lineups, recommended against Yahoo's as read, and the held slots (#107). */
  lineup: (league: string, system: ProjectionSystem, week?: number) =>
    request<LineupPayload>(`/seasons/${encodeURIComponent(league)}/lineup?system=${system}${week == null ? "" : `&week=${week}`}`),
  /** Every week left of my season as win odds, each with its scoreboard and my players (#116). */
  outlook: (league: string, system: ProjectionSystem) =>
    request<OutlookPayload>(`/seasons/${encodeURIComponent(league)}/outlook?system=${system}`),
  /** The best recommended move when today's moves are solved (#108); never solves them. */
  best: (league: string, system: ProjectionSystem) =>
    request<BestMove>(`/seasons/${encodeURIComponent(league)}/best?system=${system}`),
  /** Solve today's moves and give the best recommended move. */
  solveBest: (league: string, system: ProjectionSystem) =>
    request<BestMove>(`/seasons/${encodeURIComponent(league)}/best?system=${system}`, { method: "POST" }),
  /** The move drawer: adding ``player`` for ``drop`` (null: an open spot). */
  move: (league: string, player: number, drop: number | null, system: ProjectionSystem) =>
    request<MoveDetail>(
      `/seasons/${encodeURIComponent(league)}/moves/${player}?system=${system}${drop == null ? "" : `&drop=${drop}`}`,
    ),
  /** Today's strategy run (#110), as far as it got; never solves. */
  strategy: (league: string, system: ProjectionSystem) =>
    request<StrategyPayload>(`/seasons/${encodeURIComponent(league)}/strategy?system=${system}`),
  /** Start the strategy run (or find the one with these settings). */
  solveStrategy: (league: string, system: ProjectionSystem, o: StrategyOptions = {}) =>
    request<StrategyPayload>(`/seasons/${encodeURIComponent(league)}/strategy?${strategyQuery(system, o)}`, { method: "POST" }),
  /** Both sides of a proposed trade before and after (#96); nothing is sent to Yahoo. */
  trade: (league: string, body: TradeBody) =>
    request<TradePayload>(`/seasons/${encodeURIComponent(league)}/trade`, { method: "POST", body: JSON.stringify(body) }),
  /** The weeks the weekly recorder has kept (#97), my result in each. */
  weeks: (league: string) => request<SeasonWeeks>(`/seasons/${encodeURIComponent(league)}/weeks`),
  /** The recorded weeks against the decision log, the season to date and my moves realized (#126). */
  scorecard: (league: string) => request<ScorecardPayload>(`/seasons/${encodeURIComponent(league)}/scorecard`),
  /** Every league's season against its expectation, the knob changes and the Monday notes (#129). */
  progress: () => request<ProgressPayload>("/progress"),
  /** Whether the daily updates landed (#153): the run, the exports, each league's reads and solves. */
  status: () => request<StatusPayload>("/seasons/status"),
  /** Read the league's public sources again, in the background; 409 for a private league. */
  refreshSeason: (league: string) =>
    request<{ refresh: SeasonRefresh; season: SeasonSummary }>(`/seasons/${encodeURIComponent(league)}/refresh`, { method: "POST" }),
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
  /** Every attached room, live or finished: the landing page's live-draft panel (#74). */
  rooms: () => request<RoomSummary[]>("/rooms"),
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
