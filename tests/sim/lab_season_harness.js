// SEASON SIM (#172, PR viewer): the lab's Season tab driven with a stub DOM, for
// tests/sim/test_lab.py. Usage:
//   node lab_season_harness.js SEASON_JS APP_JS MODEL_JSON VIEW_JSON EMPTY_MODEL_JSON
// The model lists one trace; /api/trace/<its name> answers VIEW_JSON, any other name 404. Prints
// one JSON object: whether the trace started by itself, the clock before and after frames, the
// days drawn with any "undefined" or "NaN" and any mark ("<x-mark") drawn unescaped, a jump, a
// week, a speed, a missing trace's words, and the empty folder's words.
"use strict";
const fs = require("fs");
const [seasonJs, appJs, modelF, viewF, emptyF] = process.argv.slice(2);
const read = (f) => JSON.parse(fs.readFileSync(f, "utf8"));
let model = read(modelF);
const view = read(viewF), empty = read(emptyF);
const out = { problems: [], marks: [], escaped: 0, start: null, clock: {}, jump: null, week: null, speed: null, missing: null, empty: null, runs_has_trace: false, ledger_has_traces: false };
const el = (id) => {
  const e = { id, hidden: false, value: "", textContent: "", className: "", style: { setProperty() {} }, classList: { toggle() {} }, addEventListener() {}, setAttribute() {}, offsetHeight: 40, offsetWidth: 90, offsetLeft: 12, offsetTop: 30, clientWidth: 360, contains: () => true, html: "" };
  Object.defineProperty(e, "innerHTML", { get() { return this.html; }, set(v) { this.html = v; } });
  return e;
};
const els = {};
const get = (id) => (els[id] = els[id] || el(id));
let frames = [];
global.document = { getElementById: get, querySelector: () => get("top"), documentElement: { style: { setProperty() {} } }, addEventListener() {}, visibilityState: "visible" };
global.window = { addEventListener() {}, innerWidth: 390, innerHeight: 800, scrollY: 0, scrollTo() {} };
global.location = { hash: "#runs", search: "" };
global.setInterval = () => 1;
global.requestAnimationFrame = (f) => { frames.push(f); return frames.length; };
global.cancelAnimationFrame = () => {};
global.performance = { now: () => 0 };
global.fetch = (url) => {
  if (url === "/api/model") return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(model) });
  const name = decodeURIComponent(url.slice("/api/trace/".length));
  if (name === view.name) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(view) });
  return Promise.resolve({ ok: false, status: 404, text: () => Promise.resolve(`no trace named '${name}'\n`) });
};
const src = fs.readFileSync(appJs, "utf8").replace('window.addEventListener("hashchange"', 'global.__render = render; window.addEventListener("hashchange"');
const tick = () => new Promise((r) => setTimeout(r, 0));
const all = () => Object.values(els).map((e) => e.html).join("");
const look = (where) => {
  const h = all();
  for (const w of ["undefined", "NaN", "[object Object]", "Infinity"]) if (h.includes(w)) out.problems.push(`${where}: "${w}" drawn`);
  if (h.includes("<x-mark")) out.marks.push(where);
  if (h.includes("&lt;x-mark&gt;")) out.escaped += 1;
};
(async () => {
  eval(fs.readFileSync(seasonJs, "utf8"));
  eval(src);
  await tick(); await tick();
  const SV = global.window.SeasonView;
  // The Runs page lists the trace, the Checks page's ledger counts it.
  look("runs");
  out.runs_has_trace = get("page").html.includes(">Traces</h2>") && get("page").html.includes('data-trace="');
  location.hash = "#checks"; global.__render(); look("checks");
  out.ledger_has_traces = get("page").html.includes('<th class="n">Traces</th>');
  // The Season tab: the trace is read and starts by itself.
  location.hash = "#season"; global.__render();
  await tick(); await tick(); await tick();
  const s0 = SV.state();
  out.start = { loaded: s0.loaded, playing: s0.playing, name: s0.name };
  look("season, first draw");
  // The clock moves when played.
  out.clock.before = SV.state().t;
  for (let k = 1; k <= 40 && frames.length; k++) { const f = frames.shift(); f(k * 50); }
  out.clock.after = SV.state().t; out.clock.playing = SV.state().playing;
  // Drawn at several days and at each step of a day.
  const N = view.days.length;
  for (const d of [0, 0.1, 0.3, 0.7, 2.1, 2.4, 3.3, 3.8, Math.floor(N / 2) + 0.5, N - 1 + 0.9]) {
    SV.act("scrub", String(d)); look(`day ${d}`);
  }
  // A jump lands on its day and pauses; a week's button goes to its first day; a speed.
  SV.act("play"); SV.act("jump", String(view.jumps[1].day));
  out.jump = { day: Math.floor(SV.state().t), playing: SV.state().playing };
  SV.act("week", "1"); out.week = SV.state().t;
  SV.act("speed", "10"); out.speed = SV.state().speed;
  // A trace that is not on file says so, escaped.
  SV.act("pick", "<x-mark>nope"); await tick(); await tick();
  out.missing = SV.state().error; look("missing trace");
  // An empty folder says so.
  SV.mount(get("season-view"), empty); out.empty = get("season-view").html; look("empty");
  console.log(JSON.stringify(out));
})().catch((e) => { out.problems.push("harness: " + e.stack); console.log(JSON.stringify(out)); });
