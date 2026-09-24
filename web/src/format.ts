import type { Scale, WinLabel } from "./api";

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
