import assert from "node:assert/strict";
import { test } from "node:test";
import { FORMULAS, fmt, hhmm, phi, shown } from "./formulas.ts";
import { TRACKS } from "./tracks/index.ts";

const num = (s: string) => Number(s.replace(/,/g, "").replace("−", "-"));
const exampleRows = (track: string, step: string) => {
  const rows = TRACKS.find((t) => t.id === track)?.steps.find((s) => s.id === step)?.example?.table?.rows;
  assert.ok(rows, `${track}/${step} has an example table`);
  return rows;
};

test("Φ is the standard normal CDF", () => {
  assert.ok(Math.abs(phi(0) - 0.5) < 1e-8);
  assert.ok(Math.abs(phi(1.96) - 0.975) < 1e-4);
  assert.ok(Math.abs(phi(-1) - 0.158655) < 1e-6);
  assert.ok(Math.abs(phi(2.5) + phi(-2.5) - 1) < 1e-12);
});

test("numbers print with commas, a true minus and the time of day", () => {
  assert.equal(fmt(1933.7, 1), "1,933.7");
  assert.equal(fmt(-0.48, 2), "−0.48");
  assert.equal(fmt(-0.001, 2), "0.00", "no minus on a zero");
  assert.equal(hhmm(570), "09:30");
  assert.equal(shown(6, "usd"), "$6");
});

test("every formula's sample recomputes, step by step, from its inputs (#282)", () => {
  for (const f of Object.values(FORMULAS)) {
    const again = f.check();
    assert.equal(again.length, f.steps.length, `${f.id}: one check per step`);
    f.steps.forEach((s, i) => assert.equal(shown(again[i], s.shown), shown(s.value, s.shown), `${f.id} step ${i + 1}: ${s.say}`));
  }
});

test("the spread samples divide by N, not N − 1, and the pool's impacts sum to zero", () => {
  const pts = [1750, 1330, 1280, 980, 720];
  const mean = pts.reduce((a, b) => a + b, 0) / pts.length;
  const sumSq = pts.reduce((a, x) => a + (x - mean) ** 2, 0);
  const spread = FORMULAS["pool-spread"].check();
  assert.equal(fmt(spread[4], 1), fmt(Math.sqrt(sumSq / pts.length), 1));
  assert.notEqual(fmt(spread[4], 1), fmt(Math.sqrt(sumSq / (pts.length - 1)), 1), "a sample SD would show another number");
  assert.equal(FORMULAS["pool-spread"].given[0].value, "1,750, 1,330, 1,280, 980, 720", "step 1's five players");
  const [p, , sumI, why] = FORMULAS["impact-spread"].check();
  assert.equal(p, 0.5);
  assert.equal(sumI, 0);
  assert.equal(why, 0);
});

test("each formula is keyed by its own id", () => {
  for (const [id, f] of Object.entries(FORMULAS)) assert.equal(f.id, id);
});

test("the pool example agrees with the z-score and impact formulas", () => {
  for (const r of exampleRows("draft", "pool")) {
    const [pts, z, m, a, imp, zfg] = r.slice(1).map(num);
    assert.equal(fmt((pts - 1150) / 380, 2), fmt(z, 2), r[0]);
    assert.equal(fmt(m - 0.47 * a, 1), fmt(imp, 1), r[0]);
    assert.equal(fmt((m - 0.47 * a) / 40, 2), fmt(zfg, 2), r[0]);
  }
});

test("the survival example agrees with the ADP formula", () => {
  for (const r of exampleRows("draft", "survival")) {
    const [adp, sd, s21, s28, cond] = r.slice(1).map(num);
    const s = 1.5 + 0.15 * adp;
    const S = (k: number) => 1 - phi((k - adp) / s);
    assert.deepEqual([fmt(s, 1), fmt(S(21), 2), fmt(S(28), 2), fmt(S(28) / S(21), 2)], [fmt(sd, 1), fmt(s21, 2), fmt(s28, 2), fmt(cond, 2)], r[0]);
  }
});

test("the objective example agrees with expected categories won, and its slope", () => {
  let sum = 0;
  for (const r of exampleRows("draft", "objective")) {
    const [t, mu, sd, z, p, slope] = r.slice(1).map(num);
    const zz = (t - mu) / sd;
    sum += phi(zz);
    const density = Math.exp(-zz * zz / 2) / Math.sqrt(2 * Math.PI);
    assert.deepEqual([fmt(zz, 2), fmt(phi(zz), 3), fmt(density / sd, 2)], [fmt(z, 2), fmt(p, 3), fmt(slope, 2)], r[0]);
  }
  assert.equal(fmt(sum, 2), "4.25", "the reading's sum");
});

test("the weekly example agrees with the category odds", () => {
  const phiOf: Record<string, number> = { PTS: 3.17, REB: 1.34, AST: 1.27, STL: 1.07 };
  let sum = 0;
  for (const r of exampleRows("moves", "weekly-odds")) {
    const [mine, theirs, lead, spread, p] = r.slice(1).map(num);
    const sd = Math.sqrt(phiOf[r[0]] * (mine + theirs));
    sum += phi((mine - theirs) / sd);
    assert.deepEqual([mine - theirs, fmt(sd, 1), fmt(phi((mine - theirs) / sd), 2)], [lead, fmt(spread, 1), fmt(p, 2)], r[0]);
  }
  assert.equal(fmt(sum, 2), "2.04", "the reading's sum");
});
