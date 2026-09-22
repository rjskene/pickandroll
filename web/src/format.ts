import { CAT_LABEL, type Cat } from "./api";

export function parsePunt(label: string): Cat[] {
  return label === "-" ? [] : (label.split("/") as Cat[]);
}

export function puntLabel(label: string): string {
  return label === "-" ? "no punt" : label.split("/").map((c) => CAT_LABEL[c as Cat]).join(" + ");
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
