import type { AvailabilitySource, Scale, SessionSummary, WinLabel } from "./api";

/** Where the survival odds come from, in a few words. */
export function oddsSource(source: AvailabilitySource): string {
  return source === "survival" ? "simulated drafts" : source === "league" ? "the league's drafts" : "the ADP formula";
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
  return `${source}${market}; spread ${s.spread_base} + ${s.spread_growth} × ADP picks.`;
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
export function adpIsStandIn(source: string): boolean {
  return source === "bbm_rank" || source === "z_total" || source === "none";
}
