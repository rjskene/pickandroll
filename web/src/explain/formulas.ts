// The formulas the cards name (#282): each one in words, formally, with every variable and a
// sample worked step by step. A sample's inputs are typed once and its steps print them; each
// step's result is typed as shown, and the test recomputes it from the inputs, so a shown
// result cannot drift. The players are fictional and the numbers made up. No React, so the
// test runs under Node.
import type { Formula, FormulaId, MathNode, SampleStep, Shown } from "./types";

// ------------------------------------------------------------------ the math helpers
const v = (s: string): MathNode => ({ v: s });
const frac = (a: MathNode, b: MathNode): MathNode => ({ frac: [a, b] });
const sub = (a: MathNode, b: MathNode): MathNode => ({ sub: [a, b] });
const sup = (a: MathNode, b: MathNode): MathNode => ({ sup: [a, b] });
const sqrt = (a: MathNode): MathNode => ({ sqrt: a });
const par = (a: MathNode): MathNode => ({ paren: a });
const big = (op: string, under?: MathNode): MathNode => ({ big: op, under });
const cases = (...rows: [MathNode, MathNode][]): MathNode => ({ cases: rows });
const PHI = "Φ";

/** The standard normal CDF, from erf (Abramowitz and Stegun 7.1.26, error under 2e-7). */
export function phi(x: number): number {
  const z = Math.abs(x) / Math.SQRT2;
  const t = 1 / (1 + 0.3275911 * z);
  const y = 1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-z * z);
  return 0.5 * (1 + (x < 0 ? -y : y));
}

/** Rounding half up, as the bid rule rounds. */
export const halfUp = (x: number): number => Math.floor(x + 0.5);

/** A number as the samples print it: thousands commas, `dp` decimals, a true minus sign. */
export function fmt(x: number, dp = 0): string {
  const s = Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
  return x < 0 && /[1-9]/.test(s) ? `−${s}` : s;
}

/** Minutes from midnight as a time of day. */
export const hhmm = (m: number): string => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(Math.round(m) % 60).padStart(2, "0")}`;

/** A sample's result as shown. */
export function shown(x: number, how: Shown): string {
  if (how === "hhmm") return hhmm(x);
  if (how === "usd") return `$${fmt(x)}`;
  return fmt(x, how.dp);
}

const step = (say: string, math: MathNode, value: number, how: Shown): SampleStep => ({ say, math, value, shown: how });
const dp = (n: number): Shown => ({ dp: n });

// ------------------------------------------------------------------ the draft
const zscore: Formula = (() => {
  const I = { x: 1750, m: 1150, s: 380 };
  const gap = I.x - I.m;
  const zpc = sub(v("z"), [v("p"), ",", v("c")]);
  return {
    id: "zscore",
    name: "The z-score of a counting total",
    what: "How many of the pool's spreads a player's total sits above the pool's mean",
    lines: [
      [zpc, "=", frac([sub(v("x"), [v("p"), ",", v("c")]), "−", sub(v("x̄"), v("c"))], sub(v("s"), v("c")))],
      [sub(v("z"), [v("p"), ", TO"]), "=", "−", frac([sub(v("x"), [v("p"), ", TO"]), "−", sub(v("x̄"), "TO")], sub(v("s"), "TO"))],
    ],
    vars: [
      { sym: zpc, meaning: "player p's score in category c, in the pool's spreads" },
      { sym: sub(v("x"), [v("p"), ",", v("c")]), meaning: "his projected total in c over the horizon" },
      { sym: sub(v("x̄"), v("c")), meaning: "the pool's mean total in c" },
      { sym: sub(v("s"), v("c")), meaning: "the pool's spread in c: its standard deviation over the pool" },
      { sym: "pool", meaning: "as many players as the league's rosters hold, by total z, rescored until it settles" },
      { sym: "TO", meaning: "turnovers: the sign flips, so higher is better in every category" },
    ],
    given: [
      { sym: v("x"), value: fmt(I.x), say: "Player A's points over the horizon" },
      { sym: v("x̄"), value: fmt(I.m), say: "the pool's mean points" },
      { sym: v("s"), value: fmt(I.s), say: "the pool's spread of points" },
    ],
    steps: [step("the gap to the pool's mean", [fmt(I.x), "−", fmt(I.m)], 600, dp(0)), step("in the pool's spreads", frac(fmt(gap), fmt(I.s)), 1.58, dp(2))],
    check: () => [I.x - I.m, (I.x - I.m) / I.s],
    source: "projections/zscores.py under src/",
  };
})();

const impact: Formula = (() => {
  const I = { m: 520, a: 1000, p: 0.47, s: 40 };
  const pool = I.p * I.a;
  const imp = I.m - pool;
  const sum = (x: string) => ["Σ", v(x)];
  return {
    id: "impact",
    name: "Impact, for a percentage",
    what: "The makes a player adds above a pool-average shooter on his own attempts, then scored like a count",
    lines: [
      [sub(v("I"), v("p")), "=", sub(v("m"), v("p")), "−", v("p̄"), "·", sub(v("a"), v("p"))],
      [v("p̄"), "=", frac(sum("m"), sum("a")), "    ", sub(v("z"), v("p")), "=", frac(sub(v("I"), v("p")), sub(v("s"), v("I")))],
      ["team %", "=", frac(sum("m"), sum("a")), "=", v("p̄"), "+", frac(sum("I"), sum("a"))],
    ],
    vars: [
      { sym: sub(v("I"), v("p")), meaning: "player p's impact: his makes above a pool-average shooter" },
      { sym: [sub(v("m"), v("p")), ", ", sub(v("a"), v("p"))], meaning: "his makes and his attempts over the horizon" },
      { sym: v("p̄"), meaning: "the pool's percentage: the pool's makes over its attempts" },
      { sym: sub(v("s"), v("I")), meaning: "the pool's spread of impact; its mean impact is zero, so z needs no mean" },
      { sym: "team %", meaning: "over a roster the sums give the team's percentage exactly: why impact adds" },
    ],
    given: [
      { sym: v("m"), value: fmt(I.m), say: "Player B's field goals made" },
      { sym: v("a"), value: fmt(I.a), say: "his field goals attempted" },
      { sym: v("p̄"), value: fmt(I.p, 3), say: "the pool's field goal percentage" },
      { sym: sub(v("s"), v("I")), value: fmt(I.s), say: "the pool's spread of impact, in makes" },
    ],
    steps: [
      step("a pool shooter's makes on his attempts", [fmt(I.p, 3), "·", fmt(I.a)], 470, dp(1)),
      step("his makes above that", [fmt(I.m), "−", fmt(pool, 1)], 50, dp(1)),
      step("in the pool's spreads", frac(fmt(imp, 1), fmt(I.s)), 1.25, dp(2)),
    ],
    check: () => [I.p * I.a, I.m - I.p * I.a, (I.m - I.p * I.a) / I.s],
    source: "projections/zscores.py under src/",
  };
})();

const poolSpread: Formula = (() => {
  // Step 1's five players, taken as a toy pool of five.
  const X = [1750, 1330, 1280, 980, 720];
  const N = X.length;
  const total = X.reduce((a, b) => a + b, 0);
  const mean = total / N;
  const gaps = X.map((x) => x - mean);
  const ss = gaps.reduce((a, g) => a + g * g, 0);
  const xpc = sub(v("x"), [v("p"), ",", v("c")]);
  const xbar = sub(v("x̄"), v("c"));
  // A square drops the sign, so the gaps print as sizes: the line fits a phone.
  const sq = (g: number): MathNode => sup(fmt(Math.abs(g)), "2");
  const plus = (xs: MathNode[]): MathNode => xs.flatMap((x, i) => (i ? ["+", x] : [x]));
  return {
    id: "pool-spread",
    name: "The pool's mean and spread of a count",
    what: "Per counting category, the pool's average total and its population standard deviation: divided by N",
    lines: [
      [xbar, "=", frac("1", v("N")), big("Σ", v("p")), xpc],
      [sub(v("s"), v("c")), "=", sqrt([frac("1", v("N")), big("Σ", v("p")), sup(par([xpc, "−", xbar]), "2")])],
    ],
    vars: [
      { sym: xpc, meaning: "player p's projected total in category c" },
      { sym: big("Σ", v("p")), meaning: "over the pool's players only; everyone else is scored against them, not counted" },
      { sym: v("N"), meaning: "the pool's size: every roster's worth, 156 for 12 teams of 13" },
      { sym: xbar, meaning: "the pool's mean total in c" },
      { sym: sub(v("s"), v("c")), meaning: "the population standard deviation: divided by N, not N − 1; the pool is all of it" },
      { sym: [sub(v("s"), v("c")), " = 0"], meaning: "a category the whole pool ties in: 1 is used, so a score never divides by zero" },
    ],
    given: [
      { sym: v("x"), value: X.map((x) => fmt(x)).join(", "), say: "points for Players A to E: a toy pool of five" },
      { sym: v("N"), value: fmt(N), say: "the pool's size" },
    ],
    steps: [
      step("the pool's points, summed", plus(X.map((x) => fmt(x))), 6060, dp(0)),
      step("the mean: divided by N", frac(fmt(total), fmt(N)), 1212, dp(0)),
      step("each gap to the mean, squared (a square drops the sign), summed", plus(gaps.map(sq)), 603880, dp(0)),
      step("the mean square: divided by N, not N − 1", frac(fmt(ss), fmt(N)), 120776, dp(0)),
      step("the spread: its square root", sqrt(fmt(ss / N)), 347.5, dp(1)),
    ],
    check: () => [total, mean, ss, ss / N, Math.sqrt(ss / N)],
    source: "projections/zscores.py · zscores, _safe_std under src/",
  };
})();

const impactSpread: Formula = (() => {
  // Made-up shooting for a toy pool of five, A to E: 2,240 makes on 4,480 attempts.
  const M = [610, 520, 460, 350, 300];
  const A = [1240, 980, 990, 760, 510];
  const N = M.length;
  const sm = M.reduce((a, b) => a + b, 0);
  const sa = A.reduce((a, b) => a + b, 0);
  const p = sm / sa;
  const I = M.map((m, i) => m - p * A[i]);
  const ss = I.reduce((a, x) => a + x * x, 0);
  const Ip = sub(v("I"), v("p"));
  const sum = (x: MathNode): MathNode => [big("Σ", v("p")), x];
  const sq = (x: number): MathNode => sup(fmt(Math.abs(x)), "2");
  const signed = (xs: number[]): MathNode => xs.flatMap((x, i) => (i === 0 ? [fmt(x)] : [x < 0 ? "−" : "+", fmt(Math.abs(x))]));
  return {
    id: "impact-spread",
    name: "The spread of impact, for a percentage",
    what: "The pool's percentage sets each impact; the impacts average to zero, so the spread is their root mean square",
    lines: [
      [v("p̄"), "=", frac(sum(sub(v("m"), v("p"))), sum(sub(v("a"), v("p")))), "    ", Ip, "=", sub(v("m"), v("p")), "−", v("p̄"), "·", sub(v("a"), v("p"))],
      [sum(Ip), "=", sum(sub(v("m"), v("p"))), "−", v("p̄"), "·", sum(sub(v("a"), v("p"))), "=", "0"],
      [sub(v("s"), v("I")), "=", sqrt([frac("1", v("N")), big("Σ", v("p")), sup(Ip, "2")])],
    ],
    vars: [
      { sym: Ip, meaning: "player p's impact: his makes above a pool-average shooter on his own attempts" },
      { sym: [sub(v("m"), v("p")), ", ", sub(v("a"), v("p"))], meaning: "his makes and his attempts over the horizon" },
      { sym: v("p̄"), meaning: "the pool's percentage: all its makes over all its attempts" },
      { sym: [sum(Ip), " = 0"], meaning: "the percentage times the pool's attempts is the pool's makes, so the mean impact is zero" },
      { sym: v("N"), meaning: "the pool's size, as for a count" },
      { sym: sub(v("s"), v("I")), meaning: "the spread of impact: the population standard deviation, its mean being zero" },
      { sym: [sub(v("s"), v("I")), " = 0"], meaning: "no spread at all: 1 is used, as for a count" },
    ],
    given: [
      { sym: v("m"), value: M.map((x) => fmt(x)).join(", "), say: "field goals made by Players A to E: a toy pool of five" },
      { sym: v("a"), value: A.map((x) => fmt(x)).join(", "), say: "their field goals attempted" },
      { sym: v("N"), value: fmt(N), say: "the pool's size" },
    ],
    steps: [
      step(`the pool's percentage: its ${fmt(sm)} makes over its ${fmt(sa)} attempts`, frac(fmt(sm), fmt(sa)), 0.5, dp(3)),
      step(`Player E's impact; A to D the same way: ${I.slice(0, 4).map((x) => fmt(x)).join(", ")}`, [fmt(M[4]), "−", fmt(p, 3), "·", fmt(A[4])], 45, dp(0)),
      step("the five impacts, summed", signed(I), 0, dp(0)),
      step("why zero: the pool's makes less its percentage times its attempts", [fmt(sm), "−", fmt(p, 3), "·", fmt(sa)], 0, dp(0)),
      step("the impacts squared (a square drops the sign), summed", I.flatMap((x, i) => (i ? ["+", sq(x)] : [sq(x)])), 5150, dp(0)),
      step("the mean square: divided by N, not N − 1", frac(fmt(ss), fmt(N)), 1030, dp(0)),
      step("the spread of impact: its square root", sqrt(fmt(ss / N)), 32.1, dp(1)),
    ],
    check: () => [p, I[4], I.reduce((a, b) => a + b, 0), sm - p * sa, ss, ss / N, Math.sqrt(ss / N)],
    source: "projections/zscores.py · zscores, _safe_std under src/",
  };
})();

const leagueBlend: Formula = (() => {
  const I = { D: 8, rec: 0.55, adp: 0.63 };
  const w = I.D / (I.D + 1);
  const Sk = (s: MathNode): MathNode => [sub(v("S"), s), "(", v("k"), ")"];
  return {
    id: "league-blend",
    name: "The league's record, shrunk toward the formula",
    what: "Each survival cell weighs the league's own drafts against the ADP formula by how many drafts there are",
    lines: [[v("S"), "(", v("k"), ")", "=", frac(v("D"), [v("D"), "+", "1"]), "·", Sk("rec"), "+", frac("1", [v("D"), "+", "1"]), "·", Sk("ADP")]],
    vars: [
      { sym: [v("S"), "(", v("k"), ")"], meaning: "the chance he is still on the board at overall pick k" },
      { sym: Sk("rec"), meaning: "the share of the league's drafts with him still there at k, by keeper-adjusted ADP" },
      { sym: Sk("ADP"), meaning: "the ADP formula's chance at the same pick" },
      { sym: v("D"), meaning: "the drafts on record, by weight: a draft of another format counts for less" },
    ],
    given: [
      { sym: v("D"), value: fmt(I.D), say: "drafts on record" },
      { sym: sub(v("S"), "rec"), value: fmt(I.rec, 2), say: "the record's share at pick 28" },
      { sym: sub(v("S"), "ADP"), value: fmt(I.adp, 2), say: "the formula's chance at pick 28" },
    ],
    steps: [
      step("the record's weight", frac(fmt(I.D), [fmt(I.D), "+", "1"]), 0.889, dp(3)),
      step("the blend", [fmt(w, 3), "·", fmt(I.rec, 2), "+", fmt(1 - w, 3), "·", fmt(I.adp, 2)], 0.56, dp(2)),
    ],
    check: () => [I.D / (I.D + 1), (I.D / (I.D + 1)) * I.rec + (1 / (I.D + 1)) * I.adp],
    source: "availability/league.py under src/",
  };
})();

const adpSurvival: Formula = (() => {
  const I = { a: 30, n: 21, k: 28 };
  const s = 1.5 + 0.15 * I.a;
  const S = (k: number) => 1 - phi((k - I.a) / s);
  const at = (k: number): MathNode => ["1", "−", PHI, par(frac([fmt(k), "−", fmt(I.a)], fmt(s, 1)))];
  return {
    id: "adp-survival",
    name: "Survival from ADP",
    what: "The chance a player is still on the board at a pick, from a normal draft slot around his ADP",
    lines: [
      [v("S"), "(", v("k"), ")", "=", "1", "−", PHI, par(frac([v("k"), "−", v("a")], v("s")))],
      [v("s"), "=", "1.5", "+", "0.15", v("a")],
      [v("S"), "(", v("k"), " | ", v("n"), ")", "=", frac([v("S"), "(", v("k"), ")"], [v("S"), "(", v("n"), ")"])],
    ],
    vars: [
      { sym: v("k"), meaning: "the overall pick asked about: my next pick" },
      { sym: v("n"), meaning: "the overall pick now" },
      { sym: v("a"), meaning: "his ADP, shifted by the league's ADP bias where one is fitted" },
      { sym: v("s"), meaning: "the spread of his draft slot, in picks: wider for a later ADP" },
      { sym: PHI, meaning: "the standard normal CDF: the chance a normal draw falls below" },
      { sym: [v("S"), "(", v("k"), ")"], meaning: "the chance he lasts to pick k, counted from pick one" },
      { sym: [v("S"), "(", v("k"), " | ", v("n"), ")"], meaning: "the same, given he is on the board now: the one the plan uses" },
    ],
    given: [
      { sym: v("a"), value: fmt(I.a), say: "Player C's ADP, no bias" },
      { sym: v("n"), value: fmt(I.n), say: "my pick now" },
      { sym: v("k"), value: fmt(I.k), say: "my next pick" },
    ],
    steps: [
      step("his spread", [fmt(1.5, 1), "+", fmt(0.15, 2), "·", fmt(I.a)], 6, dp(1)),
      step("lasts to 28, from pick one", at(I.k), 0.63, dp(2)),
      step("lasts to 21, from pick one", at(I.n), 0.93, dp(2)),
      step("lasts from 21 to 28", frac(fmt(S(I.k), 2), fmt(S(I.n), 2)), 0.68, dp(2)),
    ],
    check: () => [s, S(I.k), S(I.n), S(I.k) / S(I.n)],
    source: "availability/adp.py under src/",
  };
})();

const ecw: Formula = (() => {
  const C: [string, number, number, number][] = [
    ["PTS", 6.2, 4.0, 3.0],
    ["REB", 1.0, 4.0, 3.2],
    ["AST", 4.5, 4.0, 2.8],
  ];
  const P = C.map(([, t, m, s]) => phi((t - m) / s));
  const one = ([, t, m, s]: [string, number, number, number]): MathNode => [PHI, par(frac([fmt(t, 1), "−", fmt(m, 1)], fmt(s, 1)))];
  const c = v("c");
  return {
    id: "ecw",
    name: "Expected categories won",
    what: "In each category, the chance the roster's total beats a team drawn from the league; summed, and maximized",
    lines: [[v("E"), "=", big("Σ", c), PHI, par(frac([sub(v("T"), c), "−", sub(v("μ"), c)], sub(v("σ"), c)))]],
    vars: [
      { sym: v("E"), meaning: "expected categories won: what the plan maximizes over the rosters it can draft" },
      { sym: c, meaning: "each of the nine categories" },
      { sym: sub(v("T"), c), meaning: "the roster's projected total z in c" },
      { sym: [sub(v("μ"), c), ", ", sub(v("σ"), c)], meaning: "the league's mean and spread of team totals in c: the curve" },
      { sym: PHI, meaning: "the standard normal CDF: the chance a total of T beats a drawn team" },
    ],
    given: C.map(([name, t, m, s]) => ({
      sym: [sub(v("T"), name), ", ", sub(v("μ"), name), ", ", sub(v("σ"), name)],
      value: `${fmt(t, 1)}, ${fmt(m, 1)}, ${fmt(s, 1)}`,
      say: `${name}: the roster's total, the league's mean and spread`,
    })),
    steps: [
      step("points", one(C[0]), 0.77, dp(2)),
      step("rebounds", one(C[1]), 0.17, dp(2)),
      step("assists", one(C[2]), 0.57, dp(2)),
      step("three of the nine, summed; the rest add the same way", [fmt(P[0], 2), "+", fmt(P[1], 2), "+", fmt(P[2], 2)], 1.51, dp(2)),
    ],
    check: () => [...P, P[0] + P[1] + P[2]],
    source: "optim/objective.py under src/",
  };
})();

const piecewisePhi: Formula = (() => {
  const I = { z: 0.75, lo: 0.5, hi: 1.5 };
  const a = phi(I.lo);
  const b = phi(I.hi);
  const t = (I.z - I.lo) / (I.hi - I.lo);
  const line = a + t * (b - a);
  const bi = sub(v("b"), v("i"));
  const bj = sub(v("b"), [v("i"), "+1"]);
  return {
    id: "piecewise-phi",
    name: "The S-curve in straight pieces",
    what: "A solver needs straight lines, so Φ is joined between fixed points; between two of them it is a line",
    lines: [
      [v("f"), "(", v("z"), ")", "=", PHI, "(", bi, ")", "+", frac([v("z"), "−", bi], [bj, "−", bi]), "·", par([PHI, "(", bj, ")", "−", PHI, "(", bi, ")"])],
      [v("z"), "=", frac([v("T"), "−", v("μ")], v("σ"))],
      [v("b"), "∈", "{−2.5, −1.5, −0.5, 0.5, 1.5, 2.5}"],
    ],
    vars: [
      { sym: v("z"), meaning: "the total in spreads from the league's mean" },
      { sym: [bi, ", ", bj], meaning: "the breakpoints either side of z" },
      { sym: [v("f"), "(", v("z"), ")"], meaning: "the straight-line value the solver carries in place of Φ(z)" },
      { sym: "outside", meaning: "past the outer points the line runs to the lowest and highest totals the roster can reach" },
      { sym: "binaries", meaning: "one per breakpoint and category keeps the pieces filling in order" },
    ],
    given: [{ sym: v("z"), value: fmt(I.z, 2), say: "a total three quarters of a spread above the mean" }],
    steps: [
      step("Φ at the break below", [PHI, "(", fmt(I.lo, 1), ")"], 0.6915, dp(4)),
      step("Φ at the break above", [PHI, "(", fmt(I.hi, 1), ")"], 0.9332, dp(4)),
      step("how far between them", frac([fmt(I.z, 2), "−", fmt(I.lo, 1)], [fmt(I.hi, 1), "−", fmt(I.lo, 1)]), 0.25, dp(2)),
      step("the straight line", [fmt(a, 4), "+", fmt(t, 2), "·", par([fmt(b, 4), "−", fmt(a, 4)])], 0.7519, dp(4)),
      step("the curve itself", [PHI, "(", fmt(I.z, 2), ")"], 0.7734, dp(4)),
      step("the line falls short by", [fmt(phi(I.z), 4), "−", fmt(line, 4)], 0.0215, dp(4)),
    ],
    check: () => [phi(I.lo), phi(I.hi), (I.z - I.lo) / (I.hi - I.lo), phi(I.lo) + ((I.z - I.lo) / (I.hi - I.lo)) * (phi(I.hi) - phi(I.lo)), phi(I.z), phi(I.z) - line],
    source: "optim/objective.py under src/",
  };
})();

const planValue: Formula = (() => {
  const I = { zc: 4.0, ac: 0.68, zd: 3.2, ad: 0.97 };
  const c = v("c");
  const pc = [v("p"), ",", c];
  const pj = [v("p"), ",", v("j")];
  return {
    id: "plan-value",
    name: "A planned pick's value",
    what: "A player planned for a later pick counts only as far as he is likely to be there",
    lines: [[sub(v("T"), c), "=", big("Σ", v("j")), big("Σ", v("p")), sub(v("z"), pc), sub(v("A"), pj), sub(v("y"), pj), "+", big("Σ", v("l")), sub(v("z"), [v("l"), ",", c])]],
    vars: [
      { sym: v("j"), meaning: "each of my remaining picks" },
      { sym: v("p"), meaning: "each available player" },
      { sym: sub(v("z"), pc), meaning: "his z in category c" },
      { sym: sub(v("A"), pj), meaning: "the chance he lasts to my j-th pick, read from now: 1 for the pick on the clock" },
      { sym: sub(v("y"), pj), meaning: "1 when he is the plan for pick j, else 0: one player a pick, a player once" },
      { sym: v("l"), meaning: "the players already mine, keepers included, counted in full" },
      { sym: sub(v("T"), c), meaning: "the roster's expected total in c: what the objective scores" },
    ],
    given: [
      { sym: sub(v("z"), "C"), value: fmt(I.zc, 1), say: "Player C's total z, the nine summed for brevity" },
      { sym: sub(v("A"), "C"), value: fmt(I.ac, 2), say: "his chance to last to my pick 28" },
      { sym: sub(v("z"), "D"), value: fmt(I.zd, 1), say: "Player D's total z" },
      { sym: sub(v("A"), "D"), value: fmt(I.ad, 2), say: "his chance to last to my pick 28" },
    ],
    steps: [
      step("Player C at pick 28", [fmt(I.zc, 1), "·", fmt(I.ac, 2)], 2.72, dp(2)),
      step("Player D at pick 28", [fmt(I.zd, 1), "·", fmt(I.ad, 2)], 3.1, dp(2)),
      step("Player D ahead, so the plan takes him", [fmt(I.zd * I.ad, 2), "−", fmt(I.zc * I.ac, 2)], 0.38, dp(2)),
    ],
    check: () => [I.zc * I.ac, I.zd * I.ad, I.zd * I.ad - I.zc * I.ac],
    source: "optim/horizon.py under src/",
  };
})();

const price: Formula = (() => {
  const I = { best: 7.42, b: 7.39, c: 7.21 };
  const Ei = sub(sup(v("E"), "*"), v("i"));
  return {
    id: "price",
    name: "A candidate's price",
    what: "Force the candidate to be my pick now and solve again; the categories lost are his price",
    lines: [
      [sub("price", v("i")), "=", sup(v("E"), "*"), "−", Ei],
      ["a tie when", " ", sub("price", v("i")), "≤", "0.05"],
    ],
    vars: [
      { sym: sup(v("E"), "*"), meaning: "the best plan's expected categories won, nothing forced" },
      { sym: Ei, meaning: "the same with candidate i forced to be my pick now" },
      { sym: sub("price", v("i")), meaning: "the categories lost by taking i now; waiting's risk is already in the plan" },
      { sym: "0.05", meaning: "the tie band: candidates within it are listed in ADP order" },
    ],
    given: [
      { sym: sup(v("E"), "*"), value: fmt(I.best, 2), say: "the best plan" },
      { sym: sub(sup(v("E"), "*"), "B"), value: fmt(I.b, 2), say: "with Player B forced first" },
      { sym: sub(sup(v("E"), "*"), "C"), value: fmt(I.c, 2), say: "with Player C forced first" },
    ],
    steps: [step("Player B's price: a tie", [fmt(I.best, 2), "−", fmt(I.b, 2)], 0.03, dp(2)), step("Player C's price", [fmt(I.best, 2), "−", fmt(I.c, 2)], 0.21, dp(2))],
    check: () => [I.best - I.b, I.best - I.c],
    source: "optim/horizon.py and api/solver.py under src/",
  };
})();

const snake: Formula = (() => {
  const I = { N: 12, p: 9, r1: 5, r2: 10 };
  const rm1 = (r: MathNode): MathNode => par([r, "−", "1"]);
  return {
    id: "snake",
    name: "A snake draft's overall pick",
    what: "Odd rounds run from position 1 to N, even rounds back from N to 1",
    lines: [
      [
        v("o"),
        "(",
        v("r"),
        ",",
        v("p"),
        ")",
        "=",
        cases([[rm1(v("r")), v("N"), "+", v("p")], [v("r"), " odd"]], [[rm1(v("r")), v("N"), "+", v("N"), "+", "1", "−", v("p")], [v("r"), " even"]]),
      ],
    ],
    vars: [
      { sym: v("o"), meaning: "the overall pick" },
      { sym: v("r"), meaning: "the round" },
      { sym: v("p"), meaning: "the draft position, 1 to N" },
      { sym: v("N"), meaning: "the teams" },
    ],
    given: [
      { sym: v("N"), value: fmt(I.N), say: "teams" },
      { sym: v("p"), value: fmt(I.p), say: "the keepers' team's draft position" },
      { sym: v("r"), value: `${I.r1} and ${I.r2}`, say: "the keepers' rounds" },
    ],
    steps: [
      step("round 5, odd", [rm1(fmt(I.r1)), "·", fmt(I.N), "+", fmt(I.p)], 57, dp(0)),
      step("round 10, even", [rm1(fmt(I.r2)), "·", fmt(I.N), "+", fmt(I.N), "+", "1", "−", fmt(I.p)], 112, dp(0)),
    ],
    check: () => [(I.r1 - 1) * I.N + I.p, (I.r2 - 1) * I.N + I.N + 1 - I.p],
    source: "draft/state.py under src/",
  };
})();

// ------------------------------------------------------------------ moves
const categoryOdds: Formula = (() => {
  const I = { t1: 610, t2: 570, f: 3.17 };
  const v1 = I.f * I.t1;
  const v2 = I.f * I.t2;
  const sd = Math.sqrt(v1 + v2);
  const z = (I.t1 - I.t2) / sd;
  const s2 = (i: string): MathNode => sup(sub(v("σ"), i), "2");
  const root = sqrt([s2("1"), "+", s2("2")]);
  return {
    id: "category-odds",
    name: "The odds of winning a category this week",
    what: "My lead over the opponent, measured in our combined spread, read off the normal curve",
    lines: [
      [v("P"), "=", PHI, par(frac([sub(v("T"), "1"), "−", sub(v("T"), "2")], root))],
      [sup(sub(v("σ"), v("i")), "2"), "=", sub(v("φ"), v("c")), sub(v("T"), v("i"))],
      [sub(v("P"), "TO"), "=", PHI, par(frac([sub(v("T"), "2"), "−", sub(v("T"), "1")], root))],
    ],
    vars: [
      { sym: sub(v("T"), "1"), meaning: "my final in the category: the week so far plus the projected rest" },
      { sym: sub(v("T"), "2"), meaning: "the opponent's final, the same way" },
      { sym: [s2("1"), ", ", s2("2")], meaning: "the variance of each final" },
      { sym: sub(v("φ"), v("c")), meaning: "the category's fitted dispersion: variance per unit of total; points 3.17" },
      { sym: "%", meaning: "a percentage uses the binomial variance of makes on the attempts instead" },
      { sym: PHI, meaning: "the standard normal CDF" },
      { sym: v("P"), meaning: "the odds of winning the category; the nine sum to expected categories won" },
    ],
    given: [
      { sym: sub(v("T"), "1"), value: fmt(I.t1), say: "my points: so far plus the rest of the week" },
      { sym: sub(v("T"), "2"), value: fmt(I.t2), say: "the opponent's points" },
      { sym: sub(v("φ"), "PTS"), value: fmt(I.f, 2), say: "the points dispersion" },
    ],
    steps: [
      step("my variance", [fmt(I.f, 2), "·", fmt(I.t1)], 1933.7, dp(1)),
      step("the opponent's", [fmt(I.f, 2), "·", fmt(I.t2)], 1806.9, dp(1)),
      step("the combined spread", sqrt([fmt(v1, 1), "+", fmt(v2, 1)]), 61.2, dp(1)),
      step("my lead in that spread", frac([fmt(I.t1), "−", fmt(I.t2)], fmt(sd, 1)), 0.65, dp(2)),
      step("the odds of winning points", [PHI, "(", fmt(z, 2), ")"], 0.74, dp(2)),
    ],
    check: () => [v1, v2, sd, z, phi(z)],
    source: "api/season_week.py",
  };
})();

const bid: Formula = (() => {
  const I = { g: 0.42, t: 0.15, f: 2, s: 1.0, B: 40 };
  const base = Math.max(1, halfUp(I.g / I.t));
  const amount = halfUp(I.f * I.s * base);
  const gbar = v("ḡ");
  return {
    id: "bid",
    name: "A FAAB claim's bid",
    what: "The move's gain in multiples of the typical gain, at least $1, scaled by the flag, clamped to the budget",
    lines: [
      [v("m"), "=", "max", par(["1", ",", "round", par(frac(v("g"), gbar))])],
      [v("b"), "=", "min", par(["⌊", v("B"), "⌋", ",", "round", par([v("f"), "·", v("s"), "·", v("m")])])],
    ],
    vars: [
      { sym: v("g"), meaning: "the move's gain on the judging horizon, in expected categories won" },
      { sym: gbar, meaning: "the typical gain: the fortnight's median recommended move, or the plan floor at first" },
      { sym: v("m"), meaning: "the gain in typical gains, rounded, at least 1" },
      { sym: v("f"), meaning: "the flag factor: 1, or 2 for a breakout flag, 3 for a strong one" },
      { sym: v("s"), meaning: "the FAAB sizing knob, 1.0 while unset; the hill-climb may tune it" },
      { sym: v("B"), meaning: "the budget left, in dollars" },
      { sym: "round", meaning: "half up; a free agent costs $0, and a struck bid is a $0 claim" },
      { sym: v("b"), meaning: "the bid, with its reason in the queue" },
    ],
    given: [
      { sym: v("g"), value: fmt(I.g, 2), say: "the move's gain" },
      { sym: gbar, value: fmt(I.t, 2), say: "the typical gain" },
      { sym: v("f"), value: fmt(I.f), say: "a breakout flag" },
      { sym: v("s"), value: fmt(I.s, 1), say: "the sizing knob, unset" },
      { sym: v("B"), value: `$${fmt(I.B)}`, say: "the budget left" },
    ],
    steps: [
      step("the gain in typicals", frac(fmt(I.g, 2), fmt(I.t, 2)), 2.8, dp(1)),
      step("rounded, at least one", ["max", "(", "1", ",", "round", "(", fmt(I.g / I.t, 1), ")", ")"], 3, dp(0)),
      step("times the flag and the knob", ["round", "(", fmt(I.f), "·", fmt(I.s, 1), "·", fmt(base), ")"], 6, "usd"),
      step("clamped to the budget", ["min", "(", fmt(I.B), ",", fmt(amount), ")"], 6, "usd"),
    ],
    check: () => [I.g / I.t, Math.max(1, halfUp(I.g / I.t)), halfUp(I.f * I.s * Math.max(1, halfUp(I.g / I.t))), Math.min(Math.floor(I.B), amount)],
    source: "season/autopilot.py · bid_of; docs/AUTOPILOT.md",
  };
})();

const claimOdds: Formula = (() => {
  const I = { p: 4, q: 0.3 };
  return {
    id: "claim-odds",
    name: "A priority claim's odds",
    what: "In a standard-waivers league the claim wins when no team ahead of me in priority claims the player",
    lines: [[v("P"), "=", sup(par(["1", "−", v("q")]), [v("p"), "−", "1"])]],
    vars: [
      { sym: v("p"), meaning: "my waiver priority, 1 the first; p − 1 teams are ahead of me" },
      { sym: v("q"), meaning: "the assumed chance each team ahead claims the same player: an assumption, not a read" },
      { sym: v("P"), meaning: "the claim's odds, shown beside the move as assumed and kept out of the objective" },
    ],
    given: [
      { sym: v("p"), value: fmt(I.p), say: "my place in the priority order" },
      { sym: v("q"), value: fmt(I.q, 1), say: "the assumed rival rate, the default" },
    ],
    steps: [
      step("teams ahead of me", [fmt(I.p), "−", "1"], 3, dp(0)),
      step("each one passes on him", ["1", "−", fmt(I.q, 1)], 0.7, dp(1)),
      step("all of them pass", sup(fmt(1 - I.q, 1), fmt(I.p - 1)), 0.343, dp(3)),
    ],
    check: () => [I.p - 1, 1 - I.q, (1 - I.q) ** (I.p - 1)],
    source: "season/moves.py · priority_claim",
  };
})();

// ------------------------------------------------------------------ the day
const executesAt: Formula = (() => {
  const I = { q1: 5 * 60 + 40, q2: 8 * 60 + 30, e: 9 * 60, w: 60 };
  const tx = sub(v("t"), "x");
  const at = (q: number): MathNode => ["max", "(", hhmm(q), "+", "60 min", ",", hhmm(I.e), ")"];
  return {
    id: "executes-at",
    name: "When a queued entry executes",
    what: "The later of an hour after it was queued and the day's execute time; a pass acts on it from then",
    lines: [
      [tx, "=", "max", par([sub(v("t"), "q"), "+", "60 min", ",", sub(v("t"), "e")])],
      ["due when", " ", tx, "≤", "now"],
      ["and not struck, with no outcome yet"],
    ],
    vars: [
      { sym: sub(v("t"), "q"), meaning: "when the entry was queued" },
      { sym: "60 min", meaning: "the veto window: the hour the user has to strike it" },
      { sym: sub(v("t"), "e"), meaning: "the day's execute time: 07:00 Central by default, Sunday's own 22:30" },
      { sym: tx, meaning: "the earliest a pass may act on the entry" },
    ],
    given: [
      { sym: sub(v("t"), "e"), value: hhmm(I.e), say: "the user's execute time" },
      { sym: sub(v("t"), "q"), value: `${hhmm(I.q1)} and ${hhmm(I.q2)}`, say: "two entries' queue times" },
    ],
    steps: [step("the 05:40 entry", at(I.q1), 540, "hhmm"), step("the 08:30 entry", at(I.q2), 570, "hhmm")],
    check: () => [Math.max(I.q1 + I.w, I.e), Math.max(I.q2 + I.w, I.e)],
    source: "season/autopilot.py · executes_at, due",
  };
})();

export const FORMULAS: Record<FormulaId, Formula> = {
  zscore,
  impact,
  "pool-spread": poolSpread,
  "impact-spread": impactSpread,
  "league-blend": leagueBlend,
  "adp-survival": adpSurvival,
  ecw,
  "piecewise-phi": piecewisePhi,
  "plan-value": planValue,
  price,
  snake,
  "category-odds": categoryOdds,
  bid,
  "claim-odds": claimOdds,
  "executes-at": executesAt,
};
