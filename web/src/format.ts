import type { AdjustmentRow, AvailabilityBias, AvailabilitySource, BoardPlayer, CurveFit, LeagueResolved, LeagueSummary, RoomSummary, Scale, SessionSummary, SurvivalBlend, WinLabel } from "./api";

/** "blend: 1.5 drafts": the drafts behind a blended table or curve, the sum of their weights. */
export function blendLabel(drafts: number): string {
  const d = Math.round(drafts * 1000) / 1000;
  return `blend: ${d} draft${d === 1 ? "" : "s"}`;
}

/** Where the survival odds come from, in a few words. */
export function oddsSource(source: AvailabilitySource, bias?: AvailabilityBias | null, blend?: SurvivalBlend | null): string {
  if (source === "survival") return "simulated drafts";
  // The league table answers late; before its first row the formula does, shifted by the bias.
  if (source === "league") {
    const drafts = blend ? `the league's drafts (${blendLabel(blend.drafts)})` : "the league's drafts";
    return bias ? `${drafts} and the ADP formula + league bias` : drafts;
  }
  return bias ? "the ADP formula + league bias" : "the ADP formula";
}

/** A blended table's makeup: its drafts by format and how much of each cell is the ADP formula. */
export function blendDetail(blend: SurvivalBlend): string {
  const other = blend.other_format ? ` + ${blend.other_format} of the other format at ×${blend.weight}` : "";
  const prior = Math.round((1000 / (blend.drafts + 1))) / 10;
  return `${blendLabel(blend.drafts)}: ${blend.same_format} of the format${other}, ${prior}% ADP formula`;
}

/** A league session's survival as the form shows it before the session exists (#74). */
export function leagueSurvivalText(r: LeagueResolved): string {
  if (r.survival === "simulate") return `simulated drafts against the league's board${r.note ? ` (${r.note})` : ""}`;
  if (r.blend) return `the format's drafts by ADP (${blendDetail(r.blend)})`;
  return `this league's own drafts by ADP (${r.survival_file})`;
}

/** The ADP formula's shift in a clause: from which ADP, fit on which seasons, from which file. */
export function biasDetail(bias: AvailabilityBias): string {
  const seasons = bias.seasons.length ? `, fit on ${bias.seasons[0]}-${bias.seasons[bias.seasons.length - 1]}` : "";
  const weight = bias.half_life != null ? ` (half-life ${bias.half_life} season${bias.half_life === 1 ? "" : "s"})` : "";
  const source = bias.source ? ` from ${bias.source.replace(/^bias:/, "")}` : "";
  return `the ADP formula centred on ADP plus the league's bias from ADP ${bias.from_adp}${seasons}${weight}${source}`;
}

/** The session's survival odds in a sentence: where they come from and the spread they use. */
export function survivalDetail(s: SessionSummary): string {
  const source =
    s.availability_source === "survival"
      ? `simulated survival table (${s.survival.sims} drafts${s.survival.source ? `, ${s.survival.source}` : ""})`
      : s.availability_source === "league"
        ? `this league's drafts by ADP (${s.survival.source}${s.survival.blend ? `, ${blendDetail(s.survival.blend)}` : ""}), the normal model under ADP ${s.survival.from_adp} and past ADP ${s.survival.max_adp}`
        : `ADP formula (${s.adp_source})`;
  // A simulated table is read by player and overall pick; the ADP model and the league table count
  // only the market.
  const market = s.availability_source !== "survival" && s.adp_keepers_ahead ? `, read in market space (${s.adp_keepers_ahead} keepers out of the market)` : "";
  const note = s.survival.note ? ` Default: ${s.survival.note}.` : "";
  const bias = s.availability_bias ? `; ${biasDetail(s.availability_bias)}` : "";
  return `${source}${market}${bias}; spread ${s.spread_base} + ${s.spread_growth} × ADP picks.${note}`;
}

export function fmtMs(ms: number | undefined): string {
  if (ms === undefined) return "";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

export function pct(x: number | undefined | null): string {
  return `${Math.round((x ?? 0) * 100)}%`;
}

export function shortName(name: string): string {
  const parts = name.split(" ");
  return parts.length > 1 ? `${parts[0][0]}. ${parts.slice(1).join(" ")}` : name;
}

/** Colour class for a survival probability. */
export function oddsClass(p: number | undefined | null): string {
  const v = p ?? 0;
  return v >= 0.7 ? "good" : v >= 0.35 ? "accent" : "bad";
}

/** Colour class for a category's win odds. */
export function labelClass(label: WinLabel): string {
  return label === "secured" ? "good" : label === "conceded" ? "bad" : "accent";
}

export function signed(x: number, digits = 2): string {
  return `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(digits)}`;
}

/** A plan objective on its scale: categories won, or z. */
export function fmtObjective(x: number | null | undefined, scale: Scale | undefined): string {
  if (x === null || x === undefined) return "—";
  return scale === "z" ? `${x.toFixed(1)} z` : `${x.toFixed(2)} cats`;
}

/** A cost on its scale, always shown as a loss. */
export function fmtCost(x: number | null | undefined, scale: Scale | undefined, approx = false): string {
  if (x === null || x === undefined) return "—";
  const v = scale === "z" ? x.toFixed(1) : x.toFixed(2);
  return `${approx ? "≈" : ""}−${v}`;
}

/** Marginal value of one more z-point in a category, as categories won per z. */
export function fmtSlope(slope: number): string {
  return `${(slope * 100).toFixed(1)}%`;
}

/** How the session's ADP was sourced, for labels. */
export function adpLabel(source: string): string {
  if (source.startsWith("file:")) return source.slice(5);
  if (source.startsWith("yahoo")) return "Yahoo";
  if (source === "bbm_adp") return "BBM ADP column";
  if (source === "bbm_rank") return "BBM value rank, no ADP file";
  if (source === "z_total") return "rank by z, no ADP file";
  return source;
}

/** True when the ADP is a stand-in ranking rather than draft-position data. */
/** Where the ranks for players missing from the ADP list come from, in a few words. */
export function rankLabel(source: string | null): string {
  if (!source) return "";
  const [kind, file] = source.split(":", 2);
  return kind === "o_rank" ? `Yahoo's rank (o_rank, ${file})` : `ranks in ${file ?? source}`;
}

/** The ADP cell: "≈" marks a rank mapped onto the ADP scale (he is not on the list), "—" a
 * player neither list knows (placed past the end of the draft). */
export function adpCell(p: BoardPlayer): string {
  if (p.adp == null) return "";
  if (p.adp_from === "end") return "—";
  const mark = p.adp_from === "rank" ? "≈" : "";
  return p.keepers_ahead > 0 && p.adp_eff != null ? `${mark}${p.adp.toFixed(0)} → ${p.adp_eff.toFixed(0)}` : `${mark}${p.adp.toFixed(1)}`;
}

/** Where the ADP cell's number comes from, and the keepers it skips. */
export function adpTitle(p: BoardPlayer, rankSource: string | null): string | undefined {
  const from =
    p.adp_from === "rank"
      ? `not on the ADP list: ${rankLabel(rankSource)} mapped onto its scale, ADP ${p.adp?.toFixed(1)}`
      : p.adp_from === "end"
        ? "on neither the ADP list nor the rank source: placed past the end of the draft"
        : null;
  const kept =
    p.keepers_ahead > 0 && p.adp_from !== "end"
      ? `${p.adp_from === "market" ? `Yahoo ADP ${p.adp?.toFixed(1)}; ` : ""}${p.keepers_ahead > 1 ? `${p.keepers_ahead} keepers ranked ahead of him are` : "a keeper ranked ahead of him is"} out of the market, so it reaches him at ${p.adp_eff?.toFixed(1)}`
      : null;
  return [from, kept].filter(Boolean).join("; ") || undefined;
}

export function adpIsStandIn(source: string): boolean {
  return source === "bbm_rank" || source === "z_total" || source === "none";
}

/** A league's draft time for the leagues list: local day and time, and how far off it is. */
export function draftWhen(iso: string | null, now: number): string {
  if (!iso) return "draft time unknown";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const when = new Date(t).toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
  const minutes = Math.round((t - now) / 60_000);
  const span = (m: number) => (m >= 120 ? `${Math.round(m / 60)} h` : `${m} min`);
  return minutes >= 0 ? `${when} (in ${span(minutes)})` : `${when} (${span(-minutes)} ago)`;
}

/** The user's pre-arm as the leagues list shows it. */
export function armLabel(armed: { at: string } | null): string {
  if (!armed) return "not armed";
  const t = Date.parse(armed.at);
  return Number.isNaN(t) ? "armed" : `armed ${new Date(t).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}`;
}

/** The league curve's fit in a line: what it was fitted on, and the seasons the standings
 * check reads ("12 rosters from 2026; standings check 2016-17 to 2025-26"). A shared archive's
 * drafts name their league ("24 rosters from 2026 252098, 2026 31153"). */
export function curveFitNote(fit: CurveFit): string {
  const rosters = fit.seasons.reduce((n, s) => n + s.rosters, 0);
  const label = (s: CurveFit["seasons"][number]) => {
    const draft = s.league ? `${s.year} ${s.league}` : `${s.year}`;
    return s.format ? `${draft} (${s.format} ×${s.weight})` : draft;
  };
  const years = fit.seasons.map(label).join(", ");
  const unscored = fit.seasons.reduce((n, s) => n + s.picks - s.scored, 0);
  const seasons = fit.check_seasons;
  const check = seasons.length ? `standings check ${seasons[0]}${seasons.length > 1 ? ` to ${seasons[seasons.length - 1]}` : ""}` : "no standings check";
  const blend = fit.blend
    ? `; ${blendLabel(fit.blend.drafts)} toward ${fit.blend.prior_status === "ready" ? "today's simulated run" : "the static fit until today's run lands"}`
    : "";
  return `${rosters} rosters from ${years}${unscored ? ` (${unscored} picks unscored)` : ""}; ${check}${blend}`;
}

/** The room's pick clock and the plan budget it gives, for the footer's feed note (#66). */
export function clockNote(room: Pick<RoomSummary, "clock_s" | "plan_time_limit">): string {
  const plan = room.plan_time_limit != null ? `plan ${room.plan_time_limit} s` : "";
  if (room.clock_s != null) return ` · ${room.clock_s} s clock${plan ? `, ${plan}` : ""}`;
  return plan ? ` · ${plan} (fixed)` : "";
}

/** Games a team plays in a week, about: "out about four weeks" is about fifteen games (#76). */
export const GAMES_PER_WEEK = 3.75;

/** The weeks the board's "out" control offers. */
export const OUT_WEEKS = [1, 2, 3, 4, 6, 8, 12];

/** Games out for "out N weeks". */
export function weeksToGames(weeks: number): number {
  return Math.round(weeks * GAMES_PER_WEEK);
}

/** The weeks a haircut set by the board's control stands for (its note), else null. */
export function haircutWeeks(a: AdjustmentRow | null | undefined): number | null {
  const m = a?.note?.match(/^out (\d+) weeks?$/);
  return m ? Number(m[1]) : null;
}

/** A haircut in a few characters for the board row and the room view. */
export function haircutLabel(a: AdjustmentRow): string {
  const weeks = haircutWeeks(a);
  if (weeks !== null) return `out ${weeks} wk`;
  if (a.games_out != null) return `−${Math.round(a.games_out)} GP`;
  return `×${a.fraction.toFixed(2)} GP`;
}

/** The haircut in a sentence, for a hover. */
export function haircutTitle(a: AdjustmentRow): string {
  const given = a.games_out != null ? `${Math.round(a.games_out)} games out` : `${Math.round(a.fraction * 100)}% of his games`;
  const note = a.note ? ` (${a.note})` : "";
  return `games haircut: ${given}${note}, ${Math.round(a.games_left)} of ${Math.round(a.games)} projected games; his totals are scaled and z recomputed`;
}

/** Seconds as m:ss. */
export function clockText(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** What the turn flag needs of a session or a room: its board and my next draftable pick
 * (`my_picks`, keeper rounds left out, tells the snake's turnaround; a room's summary lacks it). */
export interface TurnBoard {
  next_overall: number;
  my_next_pick: number | null;
  complete: boolean;
  my_picks?: number[];
}

export interface TurnFlag {
  text: string;
  /** "warn" on my turn, in the warning colour. */
  tone: "" | "warn";
}

/** The top bar's count to my next turn (#74): the picks other teams make before it, "you're
 * next" at one, and "your pick" on my turn, "your pick, then again" when my next pick follows
 * at once (the snake's turnaround), with the pick clock's seconds left when known. Null with no
 * room attached, a complete draft, or no pick of mine left. */
export function turnFlag(board: TurnBoard, attached: boolean, clockLeftS: number | null = null): TurnFlag | null {
  if (!attached || board.complete || board.my_next_pick == null) return null;
  const ahead = board.my_next_pick - board.next_overall;
  if (ahead < 0) return null;
  if (ahead === 0) {
    const again = board.my_picks?.includes(board.next_overall + 1) ?? false;
    const clock = clockLeftS == null ? "" : ` · ${clockText(clockLeftS)} left`;
    return { text: `${again ? "your pick, then again" : "your pick"}${clock}`, tone: "warn" };
  }
  return { text: ahead === 1 ? "you're next" : `${ahead} picks to your turn`, tone: "" };
}

/** Live rooms first (my turn soonest first), finished ones after. */
export function roomOrder(rooms: RoomSummary[]): RoomSummary[] {
  const turnIn = (r: RoomSummary) => (r.complete || r.my_next_pick == null ? Infinity : r.my_next_pick - r.next_overall);
  return [...rooms].sort((a, b) => Number(a.complete) - Number(b.complete) || turnIn(a) - turnIn(b));
}

// ---------------------------------------------------------------- the landing page (#108)
/** The Layout control: auto picks the page by the drafts' dates. */
export type Layout = "auto" | "season" | "draft";
export const LAYOUTS: { id: Layout; label: string; title: string }[] = [
  { id: "auto", label: "auto", title: "The draft-season page while a league's draft runs or is less than 14 days away, else the in-season page" },
  { id: "season", label: "in season", title: "The leagues' weeks and the best move in each; the drafts folded into a line" },
  { id: "draft", label: "draft season", title: "The drafts ahead with Arm, the live drafts and a new draft; the leagues as chips" },
];
/** auto shows the draft-season page while a league's draft is this many days away or less. */
export const DRAFT_SEASON_DAYS = 14;
/** A draft's length when its league does not give the rounds and the pick clock. */
const DRAFT_MS = 4 * 3600_000;
/** Past every pick on the full clock, the draft is over after this much more. */
const DRAFT_GRACE_MS = 30 * 60_000;

/** Where a league's draft stands: ahead of its time; started with no room attached; live in an
 * attached room; finished (its room complete, or past every pick on the full clock); or with no
 * time in its settings. */
export type DraftState = "ahead" | "started" | "live" | "finished" | "unscheduled";

export function draftState(l: LeagueSummary, rooms: RoomSummary[], now: number): DraftState {
  const room = rooms.find((r) => r.draft_id === l.league);
  if (room) return room.complete ? "finished" : "live";
  const t = l.draft_time ? Date.parse(l.draft_time) : NaN;
  if (Number.isNaN(t)) return "unscheduled";
  if (t > now) return "ahead";
  const rounds = l.resolved?.rounds;
  const span = rounds && l.num_teams && l.pick_seconds ? rounds * l.num_teams * l.pick_seconds * 1000 : DRAFT_MS;
  return now < t + span + DRAFT_GRACE_MS ? "started" : "finished";
}

/** The drafts the user can still arm: ahead, started with no room, or with no time yet; the
 * soonest first. A finished draft is never among them. */
export function draftsAhead(leagues: LeagueSummary[], rooms: RoomSummary[], now: number): LeagueSummary[] {
  const when = (l: LeagueSummary) => (l.draft_time ? Date.parse(l.draft_time) : Infinity);
  return leagues.filter((l) => ["ahead", "started", "unscheduled"].includes(draftState(l, rooms, now))).sort((a, b) => when(a) - when(b));
}

/** The finished drafts, the latest first. */
export function finishedDrafts(leagues: LeagueSummary[], rooms: RoomSummary[], now: number): LeagueSummary[] {
  const when = (l: LeagueSummary) => (l.draft_time ? Date.parse(l.draft_time) : 0);
  return leagues.filter((l) => draftState(l, rooms, now) === "finished").sort((a, b) => when(b) - when(a));
}

/** The page the Layout control shows: auto is the draft-season page while a room is live or a
 * league's draft runs or is less than fourteen days away, else the in-season page. */
export function pageFor(layout: Layout, leagues: LeagueSummary[], rooms: RoomSummary[], now: number): "season" | "draft" {
  if (layout !== "auto") return layout;
  const soon = now + DRAFT_SEASON_DAYS * 86_400_000;
  const near = leagues.some((l) => {
    const state = draftState(l, rooms, now);
    return state === "started" || state === "live" || (state === "ahead" && Date.parse(l.draft_time!) < soon);
  });
  return near || rooms.some((r) => !r.complete) ? "draft" : "season";
}

/** "Sat Oct 31 · 8:00 PM", a draft's day and time on this machine's clock. */
export function draftDay(iso: string | null): string {
  if (!iso) return "time unknown";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const d = new Date(t);
  const day = d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" }).replace(",", "");
  return `${day} · ${d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}`;
}

/** "in 2 days 6 h", "in 3 h", "in 45 min", or "started 20 min ago". */
export function untilLabel(iso: string | null, now: number): string {
  const t = iso ? Date.parse(iso) : NaN;
  if (Number.isNaN(t)) return "no draft time yet";
  const minutes = Math.round((t - now) / 60_000);
  const span = (m: number) => {
    if (m < 60) return `${m} min`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h} h`;
    const days = Math.floor(h / 24);
    return `${days} day${days === 1 ? "" : "s"}${h % 24 ? ` ${h % 24} h` : ""}`;
  };
  return minutes >= 0 ? `in ${span(minutes)}` : `started ${span(-minutes)} ago`;
}

/** The league whose draft comes next, among those not yet past. */
export function nextDraft(leagues: LeagueSummary[], now: number): LeagueSummary | null {
  const upcoming = leagues
    .filter((l) => l.draft_time && Date.parse(l.draft_time) > now)
    .sort((a, b) => Date.parse(a.draft_time!) - Date.parse(b.draft_time!));
  return upcoming[0] ?? null;
}
