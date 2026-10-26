// node --test extension/test/*.test.js
// The lineup executor's dry run (#170): the team page's form read, every step's checks on it, the
// run the log takes, the strip, and the service worker's two operations. Fixtures carry Yahoo ids
// and slot codes only.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const X = require("../lib/lineup.js");

const DIR = path.join(__dirname, "..");
const LEAGUE = "100001";
const TEAM = 4;
const DAY = "2026-10-24";
const SLOTS = ["PG", "SG", "G", "SF", "PF", "F", "C", "C", "Util", "Util"];
const POSTED = Date.parse("2026-10-24T10:02:03.123Z");

const select = (name, slot, slots) => ({
  name,
  tag: "select",
  type: "select-one",
  value: slot,
  options: slots.map((s) => ({ value: s, text: s, selected: s === slot })),
});
const hidden = (name, value) => ({ name, tag: "input", type: "hidden", value, options: null });

/** My team page's form as the content script extracts it: the crumb's value never read. */
function form({ drop = [], lock = [], date = DAY } = {}) {
  const players = [
    ["1001", "PG", ["PG", "G", "Util", "BN"]],
    ["1002", "SG", ["SG", "G", "Util", "BN"]],
    ["1003", "G", ["PG", "SG", "G", "Util", "BN"]],
    ["1004", "SF", ["SF", "F", "Util", "BN"]],
    ["1005", "PF", ["PF", "F", "C", "Util", "BN"]],
    ["1006", "F", ["SF", "PF", "F", "Util", "BN"]],
    ["1007", "C", ["C", "Util", "BN"]],
    ["1008", "C", ["PF", "F", "C", "Util", "BN"]],
    ["1009", "Util", ["SG", "SF", "G", "F", "Util", "BN"]],
    ["1010", "Util", ["PF", "C", "F", "Util", "BN"]],
    ["1011", "BN", ["SF", "PF", "F", "Util", "BN"]],
    ["1012", "BN", ["PG", "G", "Util", "BN"]],
    ["1013", "IL", ["IL", "BN"]],
  ].filter(([k]) => !drop.includes(k));
  return {
    action: `/nba/${LEAGUE}/${TEAM}/editroster`,
    method: "post",
    editable: true,
    swap_method: "target",
    swap_labels: players.length,
    fields: [
      ...players.map(([k, slot, slots]) => (lock.includes(k) ? hidden(k, slot) : select(k, slot, slots))),
      hidden("date", date),
      hidden("stat1", "P"),
      hidden("stat2", "D"),
      { name: "crumb", tag: "input", type: "hidden", value: null, options: null },
      hidden("jsubmit", "Save Changes"),
    ],
  };
}

const page = { league: LEAGUE, kind: "team", team: TEAM, date: DAY };
const swap = (player, from_slot, to_slot, w, group, tip = null) => ({ player, from_slot, to_slot, with: w, tip, group });

/** The steps route's answer for the fixture's day, built from the post at ``POSTED``. */
function stepsFor(controls, steps, extra = {}) {
  return {
    league: LEAGUE,
    team: TEAM,
    date: DAY,
    page: `https://basketball.fantasysports.yahoo.com/nba/${LEAGUE}/${TEAM}?date=${DAY}`,
    mode: "dry_run",
    stop: false,
    open: true,
    reason: null,
    read: { at: "2026-10-24T10:02:03.123000+00:00", page: "dated page" },
    steps,
    skipped: [],
    target: {},
    games: null,
    tips: true,
    slots: SLOTS,
    yahoo: { ...controls.lineup },
    ...extra,
  };
}

const keys = (value, out = []) => {
  if (value && typeof value === "object") {
    for (const [k, v] of Object.entries(value)) {
      out.push(k);
      keys(v, out);
    }
  }
  return out;
};

test("a run starts only from the routine's fragments; any other visit only shows the strip", () => {
  assert.equal(X.triggerOf("#pickandroll-lineup"), "routine");
  assert.equal(X.triggerOf("#pickandroll-lineup-late"), "routine_late");
  for (const h of ["", "#", "#top", "#pickandroll", "#pickandroll-moves", null, undefined]) assert.equal(X.triggerOf(h), null);
});

test("the form reads into each player's slot, the locked players, the options and the other fields' names", () => {
  const c = X.readControls(form({ lock: ["1010"] }));
  assert.equal(c.date, DAY);
  assert.equal(c.action, `/nba/${LEAGUE}/${TEAM}/editroster`);
  assert.equal(c.lineup["1004"], "SF");
  assert.equal(c.lineup["1010"], "Util");
  assert.equal(c.lineup["1013"], "IL");
  assert.deepEqual(c.locked, [1010]);
  assert.ok(!("1010" in c.options));
  assert.deepEqual(
    c.options["1011"].map((o) => o.slot),
    ["SF", "PF", "F", "Util", "BN"],
  );
  assert.deepEqual(c.fields, ["date", "stat1", "stat2", "crumb", "jsubmit"]);
  // An option whose value is Yahoo's own code reads by its text.
  assert.equal(X.slotOf({ value: "12", text: "Util" }), "Util");
  assert.equal(X.slotOf({ value: "IL+", text: "IL+" }), "IL+");
});

test("the page must be my team's editable lineup for the steps' day", () => {
  const c = X.readControls(form());
  const s = stepsFor(c, []);
  assert.equal(X.pageProblem(page, c, s), null);
  assert.equal(X.pageProblem({ ...page, team: 5 }, c, s), "not my team's page");
  assert.equal(X.pageProblem({ ...page, kind: "players" }, c, s), "not a team page");
  assert.equal(X.pageProblem(page, null, s), "the page has no lineup form");
  assert.equal(X.pageProblem(page, { ...c, action: `/nba/${LEAGUE}/5/editroster` }, s), "the form is not my team's lineup");
  assert.equal(X.pageProblem(page, { ...c, editable: false }, s), "the page's lineup is not editable");
  assert.equal(X.pageProblem(page, { ...c, method: "get" }, s), "the form does not post");
  assert.equal(X.pageProblem(page, X.readControls(form({ date: "2026-10-25" })), s), "the page is for 2026-10-25, the steps for 2026-10-24");
});

test("matching steps pass and leave the recommended lineup; only the moved players' selects would change", () => {
  const c = X.readControls(form());
  const steps = [swap(1011, "BN", "SF", 1004, 0), swap(1012, "BN", "Util", 1009, 1)];
  const r = X.checkSteps(c, steps, SLOTS);
  assert.deepEqual(
    r.steps.map((x) => [x.player, x.outcome, x.reason]),
    [
      [1011, "would_set", null],
      [1012, "would_set", null],
    ],
  );
  assert.equal(r.after["1011"], "SF");
  assert.equal(r.after["1004"], "BN");
  assert.equal(r.after["1012"], "Util");
  assert.equal(r.after["1009"], "BN");
  assert.deepEqual(r.steps[0].control, { kind: "select", slot: "BN", options: ["SF", "PF", "F", "Util", "BN"] });
  assert.deepEqual(X.planSelects(c, r), { 1004: "BN", 1009: "BN", 1011: "SF", 1012: "Util" });
});

test("a group that touches a locked player is skipped whole and the others still pass", () => {
  const c = X.readControls(form({ lock: ["1010"] }));
  // Group 0 moves 1005 to Util and the locked 1010 to the bench; group 1 is independent.
  const steps = [swap(1011, "BN", "PF", 1005, 0), swap(1005, "BN", "Util", 1010, 0), swap(1012, "BN", "Util", 1009, 1)];
  const r = X.checkSteps(c, steps, SLOTS);
  assert.deepEqual(
    r.steps.map((x) => [x.player, x.outcome]),
    [
      [1011, "skipped"],
      [1005, "skipped"],
      [1012, "would_set"],
    ],
  );
  assert.equal(r.steps[0].reason, "player 1010's game began (his slot is fixed)");
  assert.equal(r.steps[1].reason, r.steps[0].reason);
  // The skipped group leaves its players where the page has them.
  assert.equal(r.after["1011"], "BN");
  assert.equal(r.after["1005"], "PF");
  assert.equal(r.after["1012"], "Util");
});

test("a target slot missing from the options, a moved player and a game that began fail their step", () => {
  const c = X.readControls(form());
  const now = Date.parse("2026-10-24T23:30:00Z");
  const cases = [
    [swap(1012, "BN", "SF", 1004, 0), "SF is not among player 1012's slots"],
    [swap(1011, "BN", "C", 1007, 0), "C is not among player 1011's slots"],
    [swap(1004, "BN", "SF", null, 0), "player 1004 is in SF on the page, not BN"],
    [swap(1011, "BN", "SF", 1006, 0), "player 1006 is in F on the page, not SF"],
    [swap(1099, "BN", "SF", 1004, 0), "player 1099 is not on the page"],
    [swap(1011, "BN", "SF", 1004, 0, "2026-10-24T23:00:00Z"), "player 1011's game began"],
  ];
  for (const [step, why] of cases) {
    const r = X.checkSteps(c, [step], SLOTS, now);
    assert.equal(r.steps[0].outcome, "skipped", why);
    assert.equal(r.steps[0].reason, why);
  }
  // A swap back to a slot the other player may not take.
  const r = X.checkSteps(c, [swap(1007, "C", "Util", 1009, 0)], SLOTS, now);
  assert.equal(r.steps[0].reason, "C is not among player 1009's slots");
});

test("a move into an empty starting slot needs the slot open on the page; the bench takes anyone", () => {
  const open = X.readControls(form({ drop: ["1009"] }));
  let r = X.checkSteps(open, [swap(1012, "BN", "Util", null, 0)], SLOTS);
  assert.equal(r.steps[0].outcome, "would_set");
  const full = X.readControls(form());
  r = X.checkSteps(full, [swap(1012, "BN", "Util", null, 0)], SLOTS);
  assert.equal(r.steps[0].reason, "no Util is open on the page");
  // Two moves into one open slot: the second finds it taken.
  r = X.checkSteps(open, [swap(1012, "BN", "Util", null, 0), swap(1011, "BN", "Util", null, 1)], SLOTS);
  assert.deepEqual(
    r.steps.map((x) => x.outcome),
    ["would_set", "skipped"],
  );
  r = X.checkSteps(full, [swap(1001, "PG", "BN", null, 0)], SLOTS);
  assert.equal(r.steps[0].outcome, "would_set");
});

test("the run logs what it would set, from this page's own post, and is always a dry run", () => {
  const c = X.readControls(form());
  const steps = stepsFor(c, [swap(1011, "BN", "SF", 1004, 0)], { mode: "live" });
  const checked = X.checkSteps(c, steps.steps, SLOTS);
  const run = X.dryRun({ steps, trigger: "routine", page: `/nba/${LEAGUE}/${TEAM}?date=${DAY}`, postedAt: POSTED, controls: c, checked, extension: "0.6.0" });
  assert.equal(run.mode, "dry_run");
  assert.equal(run.outcome, "would_set");
  assert.equal(run.reason, null);
  assert.equal(run.day, DAY);
  assert.equal(run.read_at, steps.read.at);
  assert.deepEqual(run.before, c.lineup);
  assert.equal(run.after["1011"], "SF");
  assert.deepEqual(run.controls.would_set, { 1004: "BN", 1011: "SF" });
  assert.deepEqual(run.controls.fields, ["date", "stat1", "stat2", "crumb", "jsubmit"]);
  assert.equal(run.message, null);
  assert.ok(run.steps.every((s) => s.outcome !== "set"));
  // Nothing keyed by the crumb anywhere: the API refuses such a run.
  assert.ok(!keys(run).some((k) => /crumb/i.test(k)));
});

test("a run is skipped when the steps were not built from this page's post, the page differs or the day is closed", () => {
  const c = X.readControls(form());
  const steps = stepsFor(c, [swap(1011, "BN", "SF", 1004, 0)]);
  const at = (postedAt, s = steps, extra = {}) => X.dryRun({ steps: s, trigger: "routine", page: "/p", postedAt, controls: c, checked: X.checkSteps(c, s.steps, SLOTS), ...extra });
  assert.equal(at(POSTED + 1000).reason, "the steps were not built from this page's own post");
  assert.equal(at(NaN).outcome, "skipped");
  assert.equal(at(POSTED, { ...steps, yahoo: { ...steps.yahoo, 1011: "SF", 1004: "BN" } }).reason, "the page's lineup is not the one read (2 players differ)");
  assert.equal(at(POSTED, { ...steps, open: false, read: null, reason: "the day takes no more changes" }).reason, "the day takes no more changes");
  assert.equal(at(POSTED, steps, { problem: "not my team's page" }).reason, "not my team's page");
  const stopped = at(POSTED, { ...steps, stop: true, steps: [] });
  assert.deepEqual([stopped.outcome, stopped.reason], ["stopped", "STOP is on (data/autopilot/STOP)"]);
  const none = at(POSTED, { ...steps, steps: [], reason: "Yahoo's lineup already starts the recommended players" });
  assert.deepEqual([none.outcome, none.reason], ["nothing_to_do", "Yahoo's lineup already starts the recommended players"]);
  const failing = at(POSTED, { ...steps, steps: [swap(1012, "BN", "SF", 1004, 0)] });
  assert.deepEqual([failing.outcome, failing.reason], ["skipped", "every step failed a check on the page"]);
  const failed = at(POSTED, steps, { error: "no answer" });
  assert.deepEqual([failed.outcome, failed.reason], ["failed", "no answer"]);
});

test("the strip says the brake, the mode and STOP, a run's outcome, or what a run would do", () => {
  const c = X.readControls(form());
  const steps = stepsFor(c, [swap(1011, "BN", "SF", 1004, 0), swap(1012, "BN", "Util", 1009, 1)]);
  const at = new Date(2026, 9, 24, 5, 2).getTime();
  assert.equal(X.stripText({ browserOff: true }), "off in this browser (the extension's settings)");
  assert.equal(X.stripText({ steps: { ...steps, mode: "off" } }), "off in this league");
  assert.equal(X.stripText({ steps: { ...steps, stop: true } }), "STOP is on: nothing runs");
  assert.equal(X.stripText({ steps }), "dry run · a run would log 2 moves (the routine's link or the side panel runs it)");
  assert.equal(X.stripText({ steps: { ...steps, steps: [], reason: "Yahoo's lineup already starts the recommended players" } }), "dry run · Yahoo's lineup already starts the recommended players");
  const run = X.dryRun({ steps, trigger: "panel", page: "/p", postedAt: POSTED, controls: c, checked: X.checkSteps(c, steps.steps, SLOTS) });
  assert.equal(X.stripText({ steps, run, at }), "dry run · 2 moves logged 05:02");
  assert.equal(X.stripText({ steps: { ...steps, mode: "live" }, run, at }), "live (this build logs only) · 2 moves logged 05:02");
  assert.equal(X.stripText({ error: "API down" }), "not reached: API down");
  assert.equal(
    X.lastRunText({ at, day: DAY, trigger: "panel", outcome: "would_set", reason: null, moves: 2 }, "3 min ago"),
    "2026-10-24 · side panel: would set 2 moves, 3 min ago",
  );
  assert.equal(X.lastRunText(null, ""), "no run from this browser yet");
});

/** worker.js in a context with a fake chrome; ``reply`` answers each fetch. */
function loadWorker(reply) {
  const listeners = [];
  const fetches = [];
  const store = new Map();
  const evt = (list) => ({ addListener: (fn) => list.push(fn) });
  const session = {
    get: async (key) => (store.has(key) ? { [key]: structuredClone(store.get(key)) } : {}),
    set: async (obj) => {
      for (const [k, v] of Object.entries(obj)) store.set(k, structuredClone(v));
    },
    remove: async (key) => {
      store.delete(key);
    },
  };
  const chrome = {
    runtime: { onMessage: evt(listeners), onConnect: evt([]), onInstalled: evt([]), onStartup: evt([]) },
    storage: { local: { get: async () => ({ api: "http://api.test", lineup_executor: "off" }) }, session },
    sidePanel: { setPanelBehavior: async () => {} },
  };
  async function fetch(url, { method, body } = {}) {
    const f = { url, method, body: body ? JSON.parse(body) : null };
    fetches.push(f);
    const [status, data] = reply(f);
    return { ok: status < 400, status, text: async () => JSON.stringify(data) };
  }
  const ctx = vm.createContext({ chrome, fetch, AbortController, setTimeout, clearTimeout, console, URL });
  ctx.self = ctx;
  ctx.importScripts = (...files) => {
    for (const f of files) vm.runInContext(fs.readFileSync(path.join(DIR, f), "utf8"), ctx);
  };
  vm.runInContext(fs.readFileSync(path.join(DIR, "worker.js"), "utf8"), ctx);
  const send = (msg) =>
    new Promise((resolve) => {
      const done = (r) => resolve(JSON.parse(JSON.stringify(r)));
      for (const fn of listeners) if (fn(msg, { tab: { id: 7 } }, done) === true) return;
      resolve(undefined);
    });
  return { send, fetches, store };
}

test("the worker fetches the day's steps, logs a run and keeps the last one for the panel", async () => {
  const c = X.readControls(form());
  const steps = stepsFor(c, [swap(1011, "BN", "SF", 1004, 0)]);
  const w = loadWorker((f) => (f.method === "POST" ? [200, { at: "x" }] : [200, steps]));
  const s = await w.send({ op: "lineup_steps", league: LEAGUE, date: DAY });
  assert.equal(s.ok, true);
  assert.equal(w.fetches[0].url, `http://api.test/seasons/${LEAGUE}/lineup/steps?date=${DAY}`);
  const run = X.dryRun({ steps, trigger: "routine", page: "/p", postedAt: POSTED, controls: c, checked: X.checkSteps(c, steps.steps, SLOTS) });
  const r = await w.send({ op: "lineup_log", league: LEAGUE, run });
  assert.equal(r.ok, true);
  assert.equal(w.fetches[1].url, `http://api.test/seasons/${LEAGUE}/autopilot/lineup`);
  assert.equal(w.fetches[1].method, "POST");
  assert.deepEqual(w.fetches[1].body, JSON.parse(JSON.stringify(run)));
  const last = w.store.get(`lineup:${LEAGUE}`);
  assert.deepEqual([last.day, last.trigger, last.outcome, last.moves], [DAY, "routine", "would_set", 1]);
  // The browser's brake is a setting the content script reads.
  const settings = await w.send({ op: "settings" });
  assert.equal(settings.data.lineup_executor, "off");
});

test("a refused run is not kept as the last one", async () => {
  const c = X.readControls(form());
  const steps = stepsFor(c, []);
  const w = loadWorker(() => [409, { detail: "the lineup executor is off in this league" }]);
  const run = X.dryRun({ steps, trigger: "panel", page: "/p", postedAt: POSTED, controls: c, checked: X.checkSteps(c, [], SLOTS) });
  const r = await w.send({ op: "lineup_log", league: LEAGUE, run });
  assert.deepEqual([r.ok, r.status, r.error], [false, 409, "the lineup executor is off in this league"]);
  assert.equal(w.store.has(`lineup:${LEAGUE}`), false);
});

test("the dry run sets no field and submits nothing; the reader loads the executor's library", () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(DIR, "manifest.json"), "utf8"));
  assert.equal(manifest.version, "0.8.1");
  const reader = manifest.content_scripts.find((c) => c.js.includes("league.js"));
  assert.deepEqual(reader.js, ["lib/league.js", "lib/lineup.js", "lib/moves.js", "league.js"]);
  // The moves executor's live claim (``fillClaim``, #171 PR 3) is the one place that touches a
  // page, and moves.test.js holds it to its three controls.
  const claim = require("../lib/moves.js").fillClaim.toString();
  for (const f of ["league.js", "lib/lineup.js", "lib/moves.js"]) {
    const src = fs.readFileSync(path.join(DIR, f), "utf8").replace(claim, "");
    assert.ok(!/\.click\(|dispatchEvent|submit\(|requestSubmit/.test(src), `${f} clicks or submits`);
    assert.ok(!/\.(value|selectedIndex|checked)\s*=[^=]/.test(src), `${f} sets a field`);
    assert.ok(!/\.selected\s*=[^=]/.test(src), `${f} selects an option`);
  }
});

/** league.js on a fake team page: the form from ``form()`` as DOM-like elements, a chrome whose
 * worker answers each op with ``answer``. Returns the messages sent, the strip and the URL. */
async function visitPage({ hash = "", answer, lock = [] }) {
  const f = form({ lock });
  const elements = f.fields.map((x) => ({
    name: x.name,
    tagName: x.tag.toUpperCase(),
    type: x.type,
    value: x.value ?? "",
    options: (x.options || []).map((o) => ({ value: o.value, textContent: ` ${o.text} `, selected: o.selected })),
  }));
  const formEl = { elements, getAttribute: (a) => ({ action: f.action, method: "post" })[a] ?? null };
  const manager = { getAttribute: (a) => ({ "data-is-editable": "true", "data-swapmethod": "target" })[a] ?? null };
  const nodes = {};
  const doc = {
    querySelector: (sel) => (sel === "form#roster-edit-form" ? formEl : sel === "section.ysf-rosterswap-manager" ? manager : null),
    querySelectorAll: (sel) => (sel === "span.pos-label[role=button]" ? new Array(13).fill({}) : []),
    getElementById: (id) => nodes[id] || null,
    createElement: () => ({ style: {}, setAttribute() {}, textContent: "" }),
    documentElement: {
      cloneNode: () => ({ querySelectorAll: () => [], outerHTML: "<html></html>" }),
      append: (el) => {
        nodes[el.id] = el;
      },
    },
  };
  const url = new URL(`https://basketball.fantasysports.yahoo.com/nba/${LEAGUE}/${TEAM}?date=${DAY}${hash}`);
  const location = { href: url.href, hash: url.hash, pathname: url.pathname, search: url.search, assign() {} };
  const sent = [];
  const replaced = [];
  const listeners = [];
  // Every league page first asks whether this tab submitted a claim awaiting its answer (#171
  // PR 3); none did here, and the lineup's own messages are kept apart.
  const landed = [];
  const chrome = {
    runtime: {
      connect: () => ({}),
      getManifest: () => ({ version: "0.6.0" }),
      onMessage: { addListener: (fn) => listeners.push(fn) },
      // Messages cross a boundary, as in Chrome: serialized (and out of the vm's realm).
      sendMessage: async (msg) => {
        if (msg.op === "moves_landed") {
          landed.push(JSON.parse(JSON.stringify(msg)));
          return { ok: true, data: null };
        }
        sent.push(JSON.parse(JSON.stringify(msg)));
        return answer(msg, sent);
      },
    },
  };
  const timers = [];
  const ctx = vm.createContext({
    chrome,
    location,
    document: doc,
    history: { replaceState: (_s, _t, u) => replaced.push(u) },
    setTimeout: (fn) => timers.push(fn),
    URL,
    Date,
    console,
  });
  ctx.window = ctx;
  ctx.globalThis = ctx;
  for (const file of ["lib/league.js", "lib/lineup.js", "lib/moves.js", "league.js"]) vm.runInContext(fs.readFileSync(path.join(DIR, file), "utf8"), ctx);
  for (const fn of timers.splice(0)) await fn();
  return { sent, strip: nodes["pickandroll-strip"], replaced, listeners, landed };
}

/** The worker's answers: the post accepted, the steps built from it, the log taking the run. */
const worker =
  (extra = {}) =>
  (msg, sent) => {
    if (msg.op === "season_page") return { ok: true, data: { post: { accepted: ["lineup/4/2026-10-24"] }, follow: null } };
    if (msg.op === "settings") return { ok: true, data: { lineup_executor: "on" } };
    if (msg.op === "lineup_steps") {
      const posted = sent.find((m) => m.op === "season_page").fetched_at;
      const c = X.readControls(form());
      const steps = stepsFor(c, [swap(1011, "BN", "SF", 1004, 0)], extra);
      return { ok: true, data: { ...steps, read: { at: new Date(posted).toISOString(), page: "dated page" } } };
    }
    if (msg.op === "lineup_log") return { ok: true, data: { at: "x" } };
    return { ok: false, error: `unexpected ${msg.op}` };
  };

test("the routine's link posts the page, checks the steps built from that post and logs a dry run", async () => {
  const v = await visitPage({ hash: "#pickandroll-lineup", answer: worker() });
  assert.deepEqual(v.landed, [{ op: "moves_landed", league: LEAGUE }]);
  assert.deepEqual(
    v.sent.map((m) => m.op),
    ["season_page", "settings", "lineup_steps", "lineup_log"],
  );
  assert.equal(v.sent[2].date, DAY);
  const run = v.sent[3].run;
  assert.deepEqual([run.mode, run.trigger, run.outcome, run.extension], ["dry_run", "routine", "would_set", "0.6.0"]);
  assert.equal(run.page, `/nba/${LEAGUE}/${TEAM}?date=${DAY}`);
  assert.deepEqual(run.controls.would_set, { 1004: "BN", 1011: "SF" });
  assert.ok(!keys(run).some((k) => /crumb/i.test(k)));
  assert.match(v.strip.textContent, /^pickandroll lineup: dry run · 1 move logged \d\d:\d\d$/);
  // The fragment is dropped so a reload is a plain visit.
  assert.deepEqual(v.replaced, [`/nba/${LEAGUE}/${TEAM}?date=${DAY}`]);
});

test("a plain visit posts the page and shows the strip; nothing is logged", async () => {
  const v = await visitPage({ answer: worker() });
  assert.deepEqual(
    v.sent.map((m) => m.op),
    ["season_page", "settings", "lineup_steps"],
  );
  assert.equal(v.strip.textContent, "pickandroll lineup: dry run · a run would log 1 move (the routine's link or the side panel runs it)");
  assert.deepEqual(v.replaced, []);
});

test("off in the league, the browser's brake and STOP: no run is logged but a stopped one", async () => {
  let v = await visitPage({ hash: "#pickandroll-lineup", answer: worker({ mode: "off", steps: [] }) });
  assert.ok(!v.sent.some((m) => m.op === "lineup_log"));
  assert.equal(v.strip.textContent, "pickandroll lineup: off in this league");
  const brake = (msg, sent) => (msg.op === "settings" ? { ok: true, data: { lineup_executor: "off" } } : worker()(msg, sent));
  v = await visitPage({ hash: "#pickandroll-lineup", answer: brake });
  assert.deepEqual(
    v.sent.map((m) => m.op),
    ["season_page", "settings"],
  );
  assert.equal(v.strip.textContent, "pickandroll lineup: off in this browser (the extension's settings)");
  v = await visitPage({ hash: "#pickandroll-lineup", answer: worker({ stop: true, steps: [] }) });
  assert.equal(v.sent[3].run.outcome, "stopped");
});

test("a page posted but not taken by the API is never run against older steps", async () => {
  const refused = (msg, sent) => (msg.op === "season_page" ? { ok: true, data: { post: { error: "API down" } } } : worker()(msg, sent));
  const v = await visitPage({ hash: "#pickandroll-lineup", answer: refused });
  const run = v.sent.find((m) => m.op === "lineup_log").run;
  assert.deepEqual([run.outcome, run.reason], ["skipped", "the steps were not built from this page's own post"]);
});

test("the side panel's button runs from a fresh post of the page", async () => {
  const v = await visitPage({ answer: worker() });
  const reply = await new Promise((resolve) => {
    for (const fn of v.listeners) if (fn({ op: "lineup_run" }, {}, resolve) === true) return;
  });
  assert.equal(reply.ok, true);
  assert.equal(reply.data.run.trigger, "panel");
  // The plain visit's post, then the button's own post before its steps.
  assert.deepEqual(
    v.sent.map((m) => m.op),
    ["season_page", "settings", "lineup_steps", "season_page", "settings", "lineup_steps", "lineup_log"],
  );
});
