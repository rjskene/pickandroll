// SEASON SIM (#172, PR lab 2): the lab's page script driven with a stub DOM, for
// tests/sim/test_lab.py. Usage: node lab_page_harness.js APP_JS MODEL_JSON NEXT_MODEL_JSON SEASON_JS
// Prints one JSON object: the renders made, any exception, any "undefined" or "NaN" drawn, any
// mark ("<x-mark") drawn unescaped in any element, and what a refresh and a failed build did.
"use strict";
const fs = require("fs");
const [app, first, next, season] = process.argv.slice(2);
const models = [JSON.parse(fs.readFileSync(first, "utf8")), JSON.parse(fs.readFileSync(next, "utf8"))];
const out = { pages: {}, renders: 0, problems: [], marks: [], escaped: 0, refresh: {} };
const el = (id) => {
  const e = { id, hidden: false, style: { setProperty() {} }, classList: { toggle() {} }, addEventListener() {}, setAttribute() {}, offsetHeight: 50, offsetWidth: 100, offsetLeft: 10, offsetTop: 10, clientWidth: 600, contains: () => true, writes: 0, html: "" };
  Object.defineProperty(e, "innerHTML", { get() { return this.html; }, set(v) { this.html = v; this.writes += 1; } });
  return e;
};
const els = {};
const get = (id) => (els[id] = els[id] || el(id));
let interval = null;
global.document = { getElementById: get, querySelector: () => get("top"), documentElement: { style: { setProperty() {} } }, addEventListener() {}, visibilityState: "visible" };
global.window = { addEventListener() {}, innerWidth: 1200, innerHeight: 800, scrollY: 0, scrollTo() {} };
global.location = { hash: "", search: "" };
global.setInterval = (f) => { interval = f; return 1; };
global.requestAnimationFrame = () => 1; global.cancelAnimationFrame = () => {}; global.performance = { now: () => 0 };
let answer = { ok: true, model: models[0] };
global.fetch = (url) => url !== "/api/model" ? Promise.resolve({ ok: false, status: 404, text: () => Promise.resolve("no trace in this harness") }) : Promise.resolve(answer.ok
  ? { ok: true, status: 200, json: () => Promise.resolve(answer.model) }
  : { ok: false, status: answer.status, text: () => Promise.resolve(answer.text) });
const src = fs.readFileSync(app, "utf8").replace('window.addEventListener("hashchange"', 'global.__render = render; global.__K = K; global.__TIPS = TIPS; window.addEventListener("hashchange"');
const tick = () => new Promise((r) => setTimeout(r, 0));
const look = (where) => {
  const h = Object.values(els).map((e) => e.html).join("") + global.__TIPS.join("");
  for (const w of ["undefined", "NaN", "[object Object]", "Infinity"]) if (h.includes(w)) out.problems.push(`${where}: "${w}" drawn`);
  if (h.includes("<x-mark")) out.marks.push(where);
  if (h.includes("&lt;x-mark&gt;")) out.escaped += 1;
};
(async () => {
  if (season) eval(fs.readFileSync(season, "utf8"));
  eval(src);
  await tick(); await tick();
  const pages = ["overview", "knobs", "checks", "runs", "season", "openings", "explainer"];
  const m = models[0];
  const rs = m.rulesets.filter((x) => x.listed && x.screen).map((x) => x.key);
  const states = [{}];
  for (const r of [...rs, "both"]) for (const o of ["measure", ...Object.keys(m.outcomes)]) for (const unit of ["raw", "se"]) for (const sort of ["lever", "strength"]) states.push({ rs: r, out: o, unit, sort });
  for (const p of pages) {
    for (const st of p === "knobs" ? states : [{}]) {
      Object.assign(global.__K, st);
      location.hash = "#" + p;
      try { global.__render(); out.renders += 1; } catch (e) { out.problems.push(`${p} ${JSON.stringify(st)}: ${e.message}`); continue; }
      look(`${p} ${JSON.stringify(st)}`);
      if (!Object.keys(st).length) out.pages[p] = get("page").html;
    }
  }
  // A refresh with the same build draws nothing; a new build draws the same tab and switches.
  location.hash = "#knobs"; Object.assign(global.__K, { sort: "strength", unit: "se", rs: rs[0] || "" }); global.__render();
  const page = get("page"), before = page.writes;
  interval(); await tick(); await tick();
  out.refresh.same_build_writes = page.writes - before;
  answer = { ok: true, model: models[1] };
  interval(); await tick(); await tick();
  out.refresh.new_build_writes = page.writes - before;
  out.refresh.kept = { hash: location.hash, sort: global.__K.sort, unit: global.__K.unit, rs: global.__K.rs };
  out.refresh.best_first_on = page.html.includes('data-v="strength" class="on"');
  // A failed build keeps the last model and says so in the header.
  const writes = page.writes;
  answer = { ok: false, status: 500, text: "the model could not be built: RuntimeError\n" };
  interval(); await tick(); await tick();
  out.refresh.failed_writes = page.writes - writes;
  out.refresh.failed_header = get("state").html;
  console.log(JSON.stringify(out));
})().catch((e) => { out.problems.push("harness: " + e.message); console.log(JSON.stringify(out)); });
