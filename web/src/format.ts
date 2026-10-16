import type { AvailabilityBias, AvailabilitySource, BoardPlayer, CurveFit, Scale, SessionSummary, WinLabel } from "./api";

/** Where the survival odds come from, in a few words. */
export function oddsSource(source: AvailabilitySource, bias?: AvailabilityBias | null): string {
  if (source === "survival") return "simulated drafts";
  // The league table answers late; before its first row the formula does, shifted by the bias.
  if (source === "league") return bias ? "the league's drafts and the ADP formula + league bias" : "the league's drafts";
  return bias ? "the ADP formula + league bias" : "the ADP formula";
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
        ? `this league's drafts by ADP (${s.survival.source}), the normal model under ADP ${s.survival.from_adp} and past ADP ${s.survival.max_adp}`
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
 * check reads ("12 rosters from 2026; standings check 2016-17 to 2025-26"). */
export function curveFitNote(fit: CurveFit): string {
  const rosters = fit.seasons.reduce((n, s) => n + s.rosters, 0);
  const years = fit.seasons.map((s) => s.year).join(", ");
  const unscored = fit.seasons.reduce((n, s) => n + s.picks - s.scored, 0);
  const seasons = fit.check_seasons;
  const check = seasons.length ? `standings check ${seasons[0]}${seasons.length > 1 ? ` to ${seasons[seasons.length - 1]}` : ""}` : "no standings check";
  return `${rosters} rosters from ${years}${unscored ? ` (${unscored} picks unscored)` : ""}; ${check}`;
}
