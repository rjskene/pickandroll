import assert from "node:assert/strict";
import { test } from "node:test";
import { GLOSSARY } from "./terms.ts";
import { FORMULAS } from "./formulas.ts";
import { BULLET_MAX, SUB_MAX, allViolations, equation, pieces, termIds, violations, visible } from "./text.ts";
import { TRACKS } from "./tracks/index.ts";
import type { Step, Track } from "./types";

const track: Track = { id: "draft", title: "t", lede: "l", labels: ["a"], steps: [] };
const step = (over: Partial<Step>): Step => ({ id: "s", title: "T", kicker: "k", figure: "export-row", bullets: [{ text: "ok" }], source: [], ...over });

test("every registered track keeps the text rule, its formulas included", () => {
  assert.deepEqual(allViolations(TRACKS, GLOSSARY, FORMULAS), []);
});

test("an equation in a card's words is reported; arithmetic words and times of day are not (#282)", () => {
  assert.equal(equation("the odds: Φ(Δ / √(σ₁² + σ₂²))"), "Φ");
  assert.equal(equation("counting: (x − mean) / spread"), ") /");
  assert.equal(equation("a per b / c"), " / ");
  assert.equal(equation("blended at D/(D+1)"), "D/(");
  assert.equal(equation("12 teams × 13 spots"), "×");
  assert.equal(equation("Window 05:00 to 06:20; IL, IL+ and NA slots"), null);
  assert.equal(equation("my lead over the opponent, measured in our combined spread"), null);
  const v = violations(track, step({ bullets: [{ text: "ok", sub: ["value = z"] }, { text: "see", formula: "nope" as never }] }), GLOSSARY, FORMULAS);
  assert.equal(v.length, 2, v.join("\n"));
  assert.match(v[0], /holds an equation/);
  assert.match(v[1], /"nope", not defined/);
});

test("a glossary definition is held to the same rule: words, not an equation (#282)", () => {
  const v = allViolations([], [{ id: "odds", term: "Odds", def: "odds (1 − q)^(p − 1) at an assumed rate" }, { id: "fine", term: "Fine", def: "the slope of the normal curve" }]);
  assert.deepEqual(v, ['glossary odds: the definition holds an equation ("^"): say it in words']);
});

test("every track has at least one step and a strip label for each", () => {
  for (const t of TRACKS) {
    assert.ok(t.steps.length >= 1, t.id);
    assert.ok(t.labels.length >= t.steps.length, t.id);
  }
});

test("the glossary is one line per term, ids unique", () => {
  const ids = new Set<string>();
  for (const g of GLOSSARY) {
    assert.ok(!ids.has(g.id), g.id);
    ids.add(g.id);
    assert.ok(!g.def.includes("\n"), g.id);
    assert.ok(g.def.length <= 160, `${g.id}: ${g.def.length}`);
  }
});

test("term markup renders as words and names the glossary id", () => {
  assert.deepEqual(pieces("a [blend] of [ecw|the nine]"), [
    { kind: "text", text: "a " },
    { kind: "term", id: "blend", text: "blend" },
    { kind: "text", text: " of " },
    { kind: "term", id: "ecw", text: "the nine" },
  ]);
  assert.equal(visible("a [blend] of [ecw|the nine]"), "a blend of the nine");
  assert.equal(visible("[execute-time]"), "execute time");
  assert.deepEqual(termIds("a [blend] of [ecw|the nine]"), ["blend", "ecw"]);
});

test("a bullet over the limit, an empty one and an unknown term are reported", () => {
  const long = "x".repeat(BULLET_MAX + 1);
  const v = violations(track, step({ bullets: [{ text: long }, { text: " " }, { text: "see [nope]" }] }), GLOSSARY);
  assert.equal(v.length, 3);
  assert.match(v[0], /over 120/);
  assert.match(v[1], /is empty/);
  assert.match(v[2], /"nope"/);
});

test("a sub-bullet over its own limit and an empty sub list are reported", () => {
  const sub = "y".repeat(SUB_MAX + 1);
  const v = violations(track, step({ bullets: [{ text: "ok", sub: [sub] }, { text: "ok", sub: [] }] }), GLOSSARY);
  assert.equal(v.length, 2);
  assert.match(v[0], /over 100/);
  assert.match(v[1], /empty sub list/);
});

test("the limit counts the words shown, not the markup", () => {
  const text = "[projection-set|" + "z".repeat(BULLET_MAX - 1) + "]";
  assert.deepEqual(violations(track, step({ bullets: [{ text }] }), GLOSSARY), []);
});

test("a track with no steps, no title or two steps of one name is reported", () => {
  assert.deepEqual(violations(track, step({ title: " ", bullets: [] }), GLOSSARY), ["draft/s: no title", "draft/s: no bullets"]);
  const twice: Track = { ...track, labels: ["a"], steps: [step({}), step({})] };
  assert.deepEqual(allViolations([twice], GLOSSARY), ["draft: 1 strip labels for 2 steps", 'draft: two steps named "s"']);
});

test("every step has a worked example, fictional players only (#282)", () => {
  for (const t of TRACKS)
    for (const s of t.steps) {
      assert.ok(s.example, `${t.id}/${s.id} has no example`);
      const all = JSON.stringify(s.example);
      for (const m of all.matchAll(/Player ([A-Z])\b/g)) assert.ok(m[1] <= "H", `${t.id}/${s.id}: Player ${m[1]}`);
      assert.doesNotMatch(all, /basketball monster|\bbbm\b|optimal/i, `${t.id}/${s.id}`);
    }
});

test("an example's long title, empty lead, short row and stray number column are reported", () => {
  const example = {
    title: "t".repeat(71),
    lead: [],
    table: { head: ["a", "b"], rows: [["1"], ["", "2"]], num: [2] },
  };
  const v = violations(track, step({ example }), GLOSSARY);
  assert.equal(v.length, 5, v.join("\n"));
  assert.match(v[0], /title is 71 characters/);
  assert.match(v[1], /sets nothing up/);
  assert.match(v[2], /row 1 has 1 cells for 2 heads/);
  assert.match(v[3], /row 2, cell 1 is empty/);
  assert.match(v[4], /number column 2/);
});
