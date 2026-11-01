// The text rule (#282) and the inline term markup, with no React, so the test runs under Node.
import type { Bullet, Step, Term, Track } from "./types";

/** A bullet is at most this many visible characters; a sub-bullet, SUB_MAX. */
export const BULLET_MAX = 120;
export const SUB_MAX = 100;

export type Piece = { kind: "text"; text: string } | { kind: "term"; id: string; text: string };

const TERM = /\[([a-z0-9-]+)(?:\|([^\]]+))?\]/g;

/** A bullet's text split into plain runs and glossary terms (`[id]`, `[id|shown as]`). */
export function pieces(text: string): Piece[] {
  const out: Piece[] = [];
  let last = 0;
  for (const m of text.matchAll(TERM)) {
    const at = m.index ?? 0;
    if (at > last) out.push({ kind: "text", text: text.slice(last, at) });
    out.push({ kind: "term", id: m[1], text: m[2] ?? m[1].replace(/-/g, " ") });
    last = at + m[0].length;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
  return out;
}

/** The words the reader sees, the term markup resolved. */
export function visible(text: string): string {
  return pieces(text)
    .map((p) => p.text)
    .join("");
}

/** The term ids a text refers to. */
export function termIds(text: string): string[] {
  return pieces(text).flatMap((p) => (p.kind === "term" ? [p.id] : []));
}

/** Every way a step breaks the rule, in words; empty when it keeps it: a bullet at most
 * BULLET_MAX visible characters and a sub-bullet at most SUB_MAX, no empty entries, every
 * term in the glossary, and two levels only (the shape allows no third). */
export function violations(track: Track, step: Step, terms: Term[]): string[] {
  const known = new Set(terms.map((t) => t.id));
  const out: string[] = [];
  const where = `${track.id}/${step.id}`;
  if (!step.title.trim()) out.push(`${where}: no title`);
  if (!step.bullets.length) out.push(`${where}: no bullets`);
  const check = (what: string, text: string, max: number) => {
    const shown = visible(text).trim();
    if (!shown) out.push(`${where}: ${what} is empty`);
    else if (shown.length > max) out.push(`${where}: ${what} is ${shown.length} characters, over ${max}: "${shown}"`);
    for (const id of termIds(text)) if (!known.has(id)) out.push(`${where}: ${what} names the term "${id}", not in the glossary`);
  };
  step.bullets.forEach((b: Bullet, i) => {
    check(`bullet ${i + 1}`, b.text, BULLET_MAX);
    (b.sub ?? []).forEach((s, j) => check(`bullet ${i + 1}, sub-bullet ${j + 1}`, s, SUB_MAX));
    if (b.sub && !b.sub.length) out.push(`${where}: bullet ${i + 1} has an empty sub list`);
  });
  return out;
}

/** The rule over every step of every track. */
export function allViolations(tracks: Track[], terms: Term[]): string[] {
  const out = tracks.flatMap((t) => t.steps.flatMap((s) => violations(t, s, terms)));
  for (const t of tracks) {
    if (t.labels.length < t.steps.length) out.push(`${t.id}: ${t.labels.length} strip labels for ${t.steps.length} steps`);
    const ids = new Set<string>();
    for (const s of t.steps) {
      if (ids.has(s.id)) out.push(`${t.id}: two steps named "${s.id}"`);
      ids.add(s.id);
    }
  }
  return out;
}
