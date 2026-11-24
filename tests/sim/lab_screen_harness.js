// SEASON SIM (#172, PR live screen): the lab's Screen tab driven with a stub DOM, for
// tests/sim/test_lab_screen.py. Usage:
//   node lab_screen_harness.js SCREEN_JS APP_JS MODEL_JSON VIEW_JSON NEXT_VIEW_JSON EMPTY_MODEL_JSON
// The model lists the screens; /api/screen/<the first view's name> answers VIEW_JSON, then
// NEXT_VIEW_JSON after the first poll, then a 500 on the second; any other name 404. Prints one
// JSON object: what the tab drew (the board's marks by kind, whether the pair and the clock
// were drawn), any "undefined" or "NaN" drawn and any mark ("<x-mark") drawn unescaped, the
// playhead before and after frames, the marks at the story's start and end, a row picked, what
// a poll and a failed poll did, and the empty model's words.
"use strict";
const fs = require("fs");
const [screenJs, appJs, modelF, viewF, nextF, emptyF] = process.argv.slice(2);
const read = (f) => JSON.parse(fs.readFileSync(f, "utf8"));
const model = read(modelF), view = read(viewF), next = read(nextF), empty = read(emptyF);
const out = { problems: [], marks: [], escaped: 0, start: null, board: {}, pair: false, clock: "", play: {}, at_start: {}, at_end: {}, pick: null, poll: {}, failed: {}, empty: null, missing: null, runs_link: false };
const el = (id) => {
  const e = { id, hidden: false, value: "", textContent: "", className: "", style: { setProperty() {} }, classList: { toggle() {} }, addEventListener() {}, setAttribute() {}, offsetHeight: 40, offsetWidth: 90, offsetLeft: 12, offsetTop: 30, clientWidth: 360, contains: () => true, html: "" };
  Object.defineProperty(e, "innerHTML", { get() { return this.html; }, set(v) { this.html = v; } });
  return e;
};
const els = {};
const get = (id) => (els[id] = els[id] || el(id));
let frames = [], intervals = [], asked = 0;
global.document = { getElementById: get, querySelector: () => get("top"), documentElement: { style: { setProperty() {} } }, addEventListener() {}, visibilityState: "visible" };
global.window = { addEventListener() {}, innerWidth: 390, innerHeight: 800, scrollY: 0, scrollTo() {} };
global.location = { hash: "#runs", search: "" };
global.setInterval = (f, ms) => { intervals.push({ f, ms }); return intervals.length; };
global.clearInterval = (k) => { if (intervals[k - 1]) intervals[k - 1].f = null; };
global.requestAnimationFrame = (f) => { frames.push(f); return frames.length; };
global.cancelAnimationFrame = () => {};
global.performance = { now: () => 0 };
global.fetch = (url) => {
  if (url === "/api/model") return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(model) });
  const name = decodeURIComponent(url.slice("/api/screen/".length));
  if (name !== view.name) return Promise.resolve({ ok: false, status: 404, text: () => Promise.resolve(`no screen named '${name}'\n`) });
  asked += 1;
  if (asked === 3) return Promise.resolve({ ok: false, status: 500, text: () => Promise.resolve("the screen could not be read: OSError\n") });
  const v = asked === 1 ? view : next;
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(v) });
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
const count = () => {
  const b = get("sc-board").html, n = (k) => (b.match(new RegExp(`class="sc-row m-${k}[ "]`, "g")) || []).length;
  return { played: n("played"), in_play: n("in-play"), waiting: n("waiting"), not_played: n("not-played") };
};
const poll = () => intervals.filter((x) => x.f).map((x) => x.ms);
(async () => {
  eval(fs.readFileSync(screenJs, "utf8"));
  eval(src);
  await tick(); await tick();
  const SC = global.window.ScreenView;
  out.runs_link = get("page").html.includes('data-screen="');
  location.hash = "#screen"; global.__render();
  await tick(); await tick(); await tick();
  const s0 = SC.state();
  out.start = { loaded: s0.loaded, live: s0.live, name: s0.name, polling: s0.polling, every: poll() };
  look("screen, first draw");
  out.board = count();
  out.pair = get("sc-pair").html.includes("The pair");
  out.clock = get("sc-now-box").html;
  // The story from its start: the marks at the start and the end.
  SC.act("scrub", "0"); look("start"); out.at_start = count();
  SC.act("scrub", String(view.story.length)); look("end"); out.at_end = count();
  // Play: the playhead moves and the reader is no longer at now.
  SC.act("scrub", "0"); SC.act("play");
  out.play.before = SC.state().t;
  for (let k = 1; k <= 30 && frames.length; k++) { const f = frames.shift(); f(k * 50); look("frame " + k); }
  out.play.after = SC.state().t; out.play.live = SC.state().live;
  // A row picked shows its two arms.
  const row = view.rows.find((r) => r.mark === "played") || view.rows[0];
  SC.act("row", row.key); look("picked");
  out.pick = { key: SC.state().pick, drawn: get("sc-pair").html.includes(row.label.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" }[c]))) };
  // Back to now; a poll brings the next read; the reader at now stays at now.
  SC.act("now");
  const live = intervals.filter((x) => x.f);
  if (live.length) { live[live.length - 1].f(); await tick(); await tick(); await tick(); }
  out.poll = { asked, board: count(), t: SC.state().t, live: SC.state().live };
  look("after a poll");
  // A failed poll keeps the last read and says so.
  const again = intervals.filter((x) => x.f);
  if (again.length) { again[again.length - 1].f(); await tick(); await tick(); await tick(); }
  out.failed = { asked, error: SC.state().error, said: get("sc-err").textContent, board: count() };
  // A screen not on file says so; an empty model says so.
  SC.act("pick", "<x-mark>nope"); await tick(); await tick();
  out.missing = SC.state().error; look("missing screen");
  SC.mount(get("screen-view"), empty); out.empty = get("screen-view").html; look("empty");
  console.log(JSON.stringify(out));
})().catch((e) => { out.problems.push("harness: " + e.stack); console.log(JSON.stringify(out)); });
