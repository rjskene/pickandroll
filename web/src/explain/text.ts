// The text rule (#282) and the inline term markup, with no React, so the test runs under Node.
import type { Bullet, Formula, FormulaId, Step, Term, Track } from "./types";

/** A bullet is at most this many visible characters; a sub-bullet, SUB_MAX. */
export const BULLET_MAX = 120;
export const SUB_MAX = 100;
/** An example's title, and its table's rows: a popout stays concise too (#282). */
export const EXAMPLE_TITLE_MAX = 70;
export const TABLE_ROWS_MAX = 10;

/** An equation in a card's words (#282): a math symbol, a spaced or bracketed division. The
 * bullet says what the formula does; its Formula chip holds the formula. */
const EQUATION = /[ΦΣ√σμΔφ²³^=≤≥×]|\s\/\s|\w\/\(|\)\s*\//;

/** Where a card's text holds an equation: the characters that give it away, or null. */
export function equation(text: string): string | null {
  const m = EQUATION.exec(visible(text));
  return m ? m[0] : null;
}

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
 * term in the glossary, and two levels only (the shape allows no third). An example keeps the
 * same rule for its bullets, a short title, and a table whose rows fill its heads. */
export function violations(track: Track, step: Step, terms: Term[], formulas?: Partial<Record<FormulaId, Formula>>): string[] {
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
  const bullets = (list: Bullet[], what: string) =>
    list.forEach((b: Bullet, i) => {
      check(`${what} ${i + 1}`, b.text, BULLET_MAX);
      (b.sub ?? []).forEach((s, j) => check(`${what} ${i + 1}, sub-bullet ${j + 1}`, s, SUB_MAX));
      if (b.sub && !b.sub.length) out.push(`${where}: ${what} ${i + 1} has an empty sub list`);
    });
  bullets(step.bullets, "bullet");
  step.bullets.forEach((b, i) => {
    for (const [what, text] of [[`bullet ${i + 1}`, b.text], ...(b.sub ?? []).map((s, j) => [`bullet ${i + 1}, sub-bullet ${j + 1}`, s])]) {
      const eq = equation(text);
      if (eq) out.push(`${where}: ${what} holds an equation ("${eq}"): say it in words, the formula goes behind a chip`);
    }
    if (b.formula && formulas && !formulas[b.formula]) out.push(`${where}: bullet ${i + 1} names the formula "${b.formula}", not defined`);
  });
  const ex = step.example;
  if (ex) {
    if (!ex.title.trim()) out.push(`${where}: the example has no title`);
    else if (ex.title.length > EXAMPLE_TITLE_MAX) out.push(`${where}: the example's title is ${ex.title.length} characters, over ${EXAMPLE_TITLE_MAX}`);
    if (!ex.lead.length) out.push(`${where}: the example sets nothing up`);
    bullets(ex.lead, "example lead");
    bullets(ex.read ?? [], "example reading");
    const tb = ex.table;
    if (tb) {
      if (!tb.head.length || !tb.rows.length) out.push(`${where}: the example's table is empty`);
      if (tb.rows.length > TABLE_ROWS_MAX) out.push(`${where}: the example's table has ${tb.rows.length} rows, over ${TABLE_ROWS_MAX}`);
      tb.rows.forEach((r, i) => {
        if (r.length !== tb.head.length) out.push(`${where}: the example's row ${i + 1} has ${r.length} cells for ${tb.head.length} heads`);
        r.forEach((c, j) => {
          if (!c.trim()) out.push(`${where}: the example's row ${i + 1}, cell ${j + 1} is empty`);
          else if (c.length > SUB_MAX) out.push(`${where}: the example's row ${i + 1}, cell ${j + 1} is ${c.length} characters, over ${SUB_MAX}`);
        });
      });
      for (const k of tb.num ?? []) if (k < 0 || k >= tb.head.length) out.push(`${where}: the example names number column ${k}, not a column`);
    }
  }
  return out;
}

/** A formula's popout under the same rule (#282): its words concise, every variable explained,
 * a sample of at least one step. */
export function formulaViolations(f: Formula): string[] {
  const out: string[] = [];
  const at = `formula ${f.id}`;
  const len = (what: string, text: string, max: number) => {
    if (!text.trim()) out.push(`${at}: ${what} is empty`);
    else if (text.length > max) out.push(`${at}: ${what} is ${text.length} characters, over ${max}`);
  };
  len("its name", f.name, EXAMPLE_TITLE_MAX);
  len("what it does", f.what, BULLET_MAX);
  if (!f.lines.length) out.push(`${at}: no definition`);
  if (!f.vars.length) out.push(`${at}: no variables`);
  f.vars.forEach((x, i) => len(`variable ${i + 1}`, x.meaning, SUB_MAX));
  f.given.forEach((g, i) => len(`input ${i + 1}`, g.say, SUB_MAX));
  if (!f.steps.length) out.push(`${at}: no sample`);
  f.steps.forEach((s, i) => len(`step ${i + 1}`, s.say, SUB_MAX));
  return out;
}

/** The rule over every step of every track; with the formulas, every chip names one, every
 * formula is named by a chip, and each keeps its own rule. */
export function allViolations(tracks: Track[], terms: Term[], formulas?: Partial<Record<FormulaId, Formula>>): string[] {
  const out = tracks.flatMap((t) => t.steps.flatMap((s) => violations(t, s, terms, formulas)));
  if (formulas) {
    const named = new Set(tracks.flatMap((t) => t.steps.flatMap((s) => s.bullets.flatMap((b) => (b.formula ? [b.formula] : [])))));
    for (const f of Object.values(formulas)) {
      if (!f) continue;
      if (!named.has(f.id)) out.push(`formula ${f.id}: no bullet names it`);
      out.push(...formulaViolations(f));
    }
  }
  for (const term of terms) {
    const eq = equation(term.def);
    if (eq) out.push(`glossary ${term.id}: the definition holds an equation ("${eq}"): say it in words`);
  }
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
