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
  // A live league whose guard refused runs dry, and the strip says so.
  const refused = { ...steps, mode: "live", live: { ok: false, reason: "STOP is on" } };
  const dry = X.dryRun({ steps: refused, trigger: "panel", page: "/p", postedAt: POSTED, controls: c, checked: X.checkSteps(c, steps.steps, SLOTS), refused: X.lineupMode(refused).refused });
  assert.equal(X.stripText({ steps: refused, run: dry, at }), "dry run · 2 moves logged 05:02 (live refused: STOP is on)");
  assert.equal(X.stripText({ steps: { ...steps, mode: "live", live: { ok: true, reason: null } } }), "live · a run would set 2 moves (the routine's link or the side panel runs it)");
  assert.equal(X.stripText({ error: "API down" }), "not reached: API down");
  assert.equal(
    X.lastRunText({ at, day: DAY, trigger: "panel", outcome: "would_set", reason: null, moves: 2 }, "3 min ago"),
    "2026-10-24 · side panel: would set 2 moves, 3 min ago",
  );
  assert.equal(X.lastRunText(null, ""), "no run from this browser yet");
});

/** worker.js in a context with a fake chrome; ``reply`` answers each fetch, ``local`` holds the
 * records the worker keeps (the settings are fixed). */
function loadWorker(reply, local = new Map()) {
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
    storage: {
      local: {
        get: async (key) =>
          typeof key === "string" ? (local.has(key) ? { [key]: structuredClone(local.get(key)) } : {}) : { api: "http://api.test", lineup_executor: "off" },
        set: async (obj) => {
          for (const [k, v] of Object.entries(obj)) local.set(k, structuredClone(v));
        },
        remove: async (key) => {
          local.delete(key);
        },
      },
      session,
    },
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

test("only the live run clicks; no field is set and nothing submitted; the reader loads the executor's library", () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(DIR, "manifest.json"), "utf8"));
  assert.equal(manifest.version, "0.11.2");
  const reader = manifest.content_scripts.find((c) => c.js.includes("league.js"));
  assert.deepEqual(reader.js, ["lib/league.js", "lib/lineup.js", "lib/moves.js", "lib/startactive.js", "lib/ilmove.js", "lib/drop.js", "league.js"]);
  // The moves executor's live claim (``fillClaim``, #171 PR 3) and Start Active's presses
  // (``pressStartActive``, #215) are the places that touch a page; moves.test.js and
  // startactive.test.js hold each to its controls.
  const claim = require("../lib/moves.js").fillClaim.toString();
  const press = require("../lib/startactive.js").pressStartActive.toString();
  const move = require("../lib/ilmove.js").moveToIL.toString();
  const drop = require("../lib/drop.js").dropPlayer.toString();
  // The lineup's live run (``swapStep``, #170 PR 3): the two clicks of a swap and its cancel.
  const swapped = X.swapStep.toString();
  for (const f of ["league.js", "lib/lineup.js", "lib/moves.js", "lib/startactive.js", "lib/ilmove.js", "lib/drop.js"]) {
    const src = fs.readFileSync(path.join(DIR, f), "utf8").replace(claim, "").replace(press, "").replace(move, "").replace(drop, "").replace(swapped, "");
    assert.ok(!/\.click\(|dispatchEvent|submit\(|requestSubmit/.test(src), `${f} clicks or submits`);
    assert.ok(!/\.(value|selectedIndex|checked)\s*=[^=]/.test(src), `${f} sets a field`);
    assert.ok(!/\.selected\s*=[^=]/.test(src), `${f} selects an option`);
  }
});

/** league.js on a fake team page: the form from ``form()`` as DOM-like elements, a chrome whose
 * worker answers each op with ``answer``. Returns the messages sent, the strip and the URL. */
async function visitPage({ hash = "", answer, lock = [], swap: roster = null }) {
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
    querySelectorAll: (sel) =>
      sel === "span.pos-label[role=button]" ? new Array(13).fill({}) : roster && [X.LINEUP_ROWS, X.LINEUP_SAVED].includes(sel) ? roster.querySelectorAll(sel) : [],
    getElementById: (id) => nodes[id] || null,
    createElement: () => ({ style: {}, setAttribute() {}, textContent: "" }),
    documentElement: {
      getAttribute: (a) => (roster ? roster.documentElement.getAttribute(a) : null),
      cloneNode: () => ({ querySelectorAll: () => [], outerHTML: "<html></html>" }),
      append: (el) => {
        nodes[el.id] = el;
      },
    },
  };
  const url = new URL(`https://basketball.fantasysports.yahoo.com/nba/${LEAGUE}/${TEAM}?date=${DAY}${hash}`);
  const assigned = [];
  const location = { href: url.href, hash: url.hash, pathname: url.pathname, search: url.search, assign: (u) => assigned.push(u) };
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
        if (msg.op === "moves_landed" || msg.op === "drop_landed") {
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
    // The page's settle runs when the test says; a live step's short waits go on at once.
    setTimeout: (fn, ms) => (ms >= 1000 ? timers.push(fn) : Promise.resolve().then(fn)),
    URL,
    Date,
    console,
  });
  ctx.window = ctx;
  ctx.globalThis = ctx;
  for (const file of ["lib/league.js", "lib/lineup.js", "lib/moves.js", "lib/startactive.js", "lib/ilmove.js", "lib/drop.js", "league.js"]) vm.runInContext(fs.readFileSync(path.join(DIR, file), "utf8"), ctx);
  for (const fn of timers.splice(0)) await fn();
  return { sent, strip: nodes["pickandroll-strip"], replaced, listeners, landed, assigned };
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
  assert.deepEqual(v.landed, [{ op: "moves_landed", league: LEAGUE }, { op: "drop_landed", league: LEAGUE }]);
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

// ---------------------------------------------------------------- the live run (#170 PR 3)
const SAVED_WORDS = "All changes saved";

/** My team page's roster as Yahoo's swap manager draws it (``ysf-rosterswapper``, swapmethod
 * "target"), from ``form()``'s players: a row per slot, ``tr.editable``, one visible
 * ``span.pos-label[role=button][data-pos]`` in an occupied row, an empty row's label hidden until
 * targeted. A click on an occupied row's label starts a swap (``swapactive`` on it, ``swaptarget``
 * on each row the two players may trade, an empty row's label shown); a click on a target's label
 * swaps the two and saves: the notice reads ``answer`` after ``after`` looks (a look is one
 * ``wait``; 0: at the click). A click on any other label while swapping leaves the swap, nothing
 * saved. ``empty`` adds empty rows of those slots; ``lockAfter`` fixes the rows of those players
 * after the first save; ``alert`` is raised on the first click; ``untargeted`` players never show
 * as a target. ``answer`` may be a list, one per save. As Yahoo's real page does (#288),
 * ``linger`` keeps ``swapactive`` on the first-clicked row for that many looks after the save
 * (Infinity: it never clears). A notice is one element; each save puts up a new one, or with
 * ``sameNotice`` rewrites the one showing in place. Clicks go in ``touched``. */
function swapDom({ drop = [], empty = [], answer = "saved", after = 1, alert = null, untargeted = [], lockAfter = [], lock = [], linger = 0, sameNotice = false } = {}) {
  const f = form({ drop });
  const eligible = {};
  const rows = [];
  for (const x of f.fields.filter((y) => /^\d+$/.test(y.name))) {
    eligible[x.name] = x.options.map((o) => o.value);
    rows.push({ slot: x.value, player: Number(x.name), editable: !lock.includes(x.name) });
  }
  for (const slot of empty) rows.push({ slot, player: null, editable: true });
  const touched = [];
  const attrs = {};
  const notices = [];
  let active = null;
  let targets = [];
  let looks = null;
  let saves = 0;
  let lingering = 0;
  const shown = new Map();
  const shownOf = (n) => {
    if (!shown.has(n))
      shown.set(n, {
        get className() {
          return n.className;
        },
        get textContent() {
          return n.textContent;
        },
        getClientRects: () => [{}],
        classList: { contains: (c) => n.className.split(" ").includes(c) },
      });
    return shown.get(n);
  };
  const may = (k, slot) => k == null || (eligible[String(k)] || []).includes(slot);
  const done = () => {
    active = null;
    targets = [];
  };
  const click = (r) => {
    touched.push(`click ${r.player ?? "empty"} ${r.slot}`);
    if (active === null) {
      if (r.player == null || !r.editable) return;
      if (alert) attrs["data-pickandroll-alerts"] = JSON.stringify([alert]);
      active = r;
      targets = rows.filter((q) => q !== r && q.editable && !untargeted.includes(q.player) && may(r.player, q.slot) && may(q.player, r.slot));
      return;
    }
    if (!targets.includes(r)) return done();
    [active.player, r.player] = [r.player, active.player];
    targets = [];
    lingering = linger;
    if (!lingering) done();
    saves += 1;
    looks = 0;
    if (after === 0) look();
  };
  const look = () => {
    if (lingering && --lingering === 0) done();
    if (looks === null) return;
    const said = Array.isArray(answer) ? answer[saves - 1] : answer;
    if (looks++ !== after || !said) return;
    const n = said === "saved" ? { className: "rostersave-msg saved", textContent: ` ${SAVED_WORDS} ` } : { className: "rostersave-msg error", textContent: "There was an error saving your changes." };
    if (sameNotice && notices.length) Object.assign(notices[0], n);
    else notices.splice(0, notices.length, n);
    if (saves === 1) for (const q of rows) if (lockAfter.includes(q.player)) q.editable = false;
  };
  const classes = (r) => [r.editable && "editable", r.player == null && "empty-bench", active === r && "swapactive", targets.includes(r) && "swaptarget"].filter(Boolean);
  const labelOf = (r) => {
    const l = {
      getAttribute: (a) => ({ "data-pos": r.slot, role: "button" })[a] ?? null,
      getClientRects: () => (r.player != null || targets.includes(r) ? [{}] : []),
      click: () => click(r),
    };
    return l;
  };
  const els = rows.map((r) => {
    const label = labelOf(r);
    return {
      classList: { contains: (c) => classes(r).includes(c) },
      querySelector: (sel) => (sel === "[data-ys-playerid]" && r.player != null ? { getAttribute: () => String(r.player) } : null),
      querySelectorAll: (sel) => (sel === X.LINEUP_LABEL ? [label] : []),
    };
  });
  return {
    touched,
    look,
    rows,
    lineup: () => Object.fromEntries(rows.filter((r) => r.player != null).map((r) => [String(r.player), r.slot])),
    querySelectorAll: (sel) =>
      sel === X.LINEUP_ROWS ? els : sel === X.LINEUP_SAVED ? notices.map(shownOf) : [],
    documentElement: { getAttribute: (a) => attrs[a] ?? null },
  };
}

const live = (dom, steps, { returns = [], stopNow, lock = [] } = {}) =>
  X.setLineup(dom, { controls: X.readControls(form({ lock })), steps, returns, slots: SLOTS }, { wait: async () => dom.look(), every: 200, showCap: 1000, saveCap: 1000, stopNow });

test("the labels read as the form does; one swap is the player's label, then his target's, then Yahoo's save", async () => {
  const dom = swapDom();
  const labels = X.readLabels(dom);
  assert.deepEqual(labels.lineup, X.readControls(form()).lineup);
  assert.deepEqual([labels.fixed, labels.twice, labels.swapping, labels.bench], [[], false, false, false]);
  const got = await live(dom, [swap(1011, "BN", "SF", 1004, 0)]);
  assert.deepEqual(dom.touched, ["click 1011 BN", "click 1004 SF"]);
  assert.deepEqual([got.outcome, got.reason], ["set", null]);
  assert.deepEqual(got.steps.map((s) => [s.player, s.kind, s.outcome, s.message]), [[1011, "swap", "set", SAVED_WORDS]]);
  assert.equal(got.after["1011"], "SF");
  assert.equal(got.after["1004"], "BN");
});

test("a group of three swaps runs in order, each checked on the page as it then reads", async () => {
  const dom = swapDom();
  const group = [swap(1011, "BN", "SF", 1004, 0), swap(1004, "BN", "Util", 1009, 0), swap(1009, "BN", "F", 1006, 0)];
  const got = await live(dom, group);
  assert.equal(got.outcome, "set");
  assert.deepEqual(dom.touched, ["click 1011 BN", "click 1004 SF", "click 1004 BN", "click 1009 Util", "click 1009 BN", "click 1006 F"]);
  assert.deepEqual([got.after["1011"], got.after["1004"], got.after["1009"], got.after["1006"]], ["SF", "Util", "F", "BN"]);
});

test("a swap that never saves, Yahoo's error or its alert fails and stops the run", async () => {
  const steps = [swap(1011, "BN", "SF", 1004, 0), swap(1012, "BN", "Util", 1010, 1)];
  let dom = swapDom({ answer: null });
  let got = await live(dom, steps);
  assert.deepEqual([got.outcome, got.reason], ["failed", "clicked; the save was not read in 1 s (0 of 2 changes set first)"]);
  assert.deepEqual(got.steps.map((s) => [s.outcome, s.reason]), [["failed", "clicked; the save was not read in 1 s"], ["skipped", "the run stopped at a failed step"]]);
  assert.deepEqual(dom.touched, ["click 1011 BN", "click 1004 SF"]);
  dom = swapDom({ answer: "error" });
  got = await live(dom, steps);
  assert.deepEqual([got.steps[0].outcome, got.steps[0].reason, got.steps[0].message], ["failed", "Yahoo did not save the swap", "There was an error saving your changes."]);
  // An alert on the first click: the swap is left by a click on the player's own label.
  dom = swapDom({ alert: "This player cannot be moved." });
  got = await live(dom, steps);
  assert.deepEqual(got.steps[0].reason, `Yahoo answered the first click: "This player cannot be moved."; the swap was cancelled`);
  assert.deepEqual(dom.touched, ["click 1011 BN", "click 1011 BN"]);
  assert.equal(X.readLabels(dom).swapping, false);
});

test("a target that never shows is cancelled with nothing saved, and the run stops", async () => {
  const dom = swapDom({ untargeted: [1004] });
  const got = await live(dom, [swap(1011, "BN", "SF", 1004, 0), swap(1012, "BN", "Util", 1010, 1)]);
  assert.equal(got.outcome, "failed");
  assert.equal(got.steps[0].reason, "player 1004's SF did not show as a target within 1 s (nothing saved; the swap was cancelled)");
  assert.deepEqual(dom.touched, ["click 1011 BN", "click 1011 BN"]);
  assert.deepEqual(dom.lineup(), X.readControls(form()).lineup);
});

test("a lock found mid-run skips its group whole; stale steps click nothing; the others still set", async () => {
  // 1012's game begins after the first save: the second group is skipped, nothing clicked for it.
  let dom = swapDom({ lockAfter: [1012] });
  let got = await live(dom, [swap(1011, "BN", "SF", 1004, 0), swap(1012, "BN", "Util", 1010, 1)]);
  assert.equal(got.outcome, "set");
  assert.equal(got.reason, "1 of 2 changes set; player 1012's game began (his slot is fixed)");
  assert.deepEqual(got.steps.map((s) => s.outcome), ["set", "skipped"]);
  assert.deepEqual(dom.touched, ["click 1011 BN", "click 1004 SF"]);
  // Steps from another read of the page: nothing clicked.
  dom = swapDom();
  got = await live(dom, [swap(1011, "SF", "BN", 1004, 0)]);
  assert.deepEqual([got.outcome, got.reason, dom.touched], ["skipped", "player 1011 is in BN on the page, not SF", []]);
  // A swap open on the page (the user's own): nothing clicked.
  dom = swapDom();
  dom.querySelectorAll(X.LINEUP_ROWS)[10].querySelectorAll(X.LINEUP_LABEL)[0].click();
  dom.touched.length = 0;
  got = await live(dom, [swap(1011, "BN", "SF", 1004, 0)]);
  assert.deepEqual([got.outcome, got.reason, dom.touched], ["skipped", "a swap is open on the page (still after 3 s)", []]);
});

test("a swap Yahoo keeps open past its save is waited out: a group of three and the groups after it all set (#288)", async () => {
  let dom = swapDom({ linger: 2 });
  const group = [swap(1011, "BN", "SF", 1004, 0), swap(1004, "BN", "Util", 1009, 0), swap(1009, "BN", "F", 1006, 0)];
  let got = await live(dom, group);
  assert.deepEqual([got.outcome, got.reason], ["set", null]);
  assert.deepEqual(got.steps.map((s) => s.outcome), ["set", "set", "set"]);
  assert.deepEqual(dom.touched, ["click 1011 BN", "click 1004 SF", "click 1004 BN", "click 1009 Util", "click 1009 BN", "click 1006 F"]);
  assert.equal(X.readLabels(dom).swapping, false);
  // Between groups: each next group waits too, none skipped.
  dom = swapDom({ linger: 3 });
  got = await live(dom, [swap(1011, "BN", "SF", 1004, 0), swap(1012, "BN", "Util", 1010, 1)]);
  assert.deepEqual([got.outcome, got.reason], ["set", null]);
  assert.deepEqual(got.steps.map((s) => s.outcome), ["set", "set"]);
  assert.deepEqual([got.after["1011"], got.after["1012"]], ["SF", "Util"]);
});

test("a swap that stays open past the bound clicks nothing more: inside a group it fails, between groups it skips (#288)", async () => {
  let dom = swapDom({ linger: Infinity });
  let got = await live(dom, [swap(1011, "BN", "SF", 1004, 0), swap(1004, "BN", "Util", 1009, 0)]);
  assert.deepEqual([got.outcome, got.reason], ["failed", "a swap is open on the page (still after 3 s) (0 of 1 change set first)"]);
  assert.deepEqual(got.steps.map((s) => s.outcome), ["set", "failed"]);
  assert.deepEqual(dom.touched, ["click 1011 BN", "click 1004 SF"]);
  dom = swapDom({ linger: Infinity });
  got = await live(dom, [swap(1011, "BN", "SF", 1004, 0), swap(1012, "BN", "Util", 1010, 1)]);
  assert.deepEqual([got.outcome, got.reason], ["set", "1 of 2 changes set; a swap is open on the page (still after 3 s)"]);
  assert.deepEqual(dom.touched, ["click 1011 BN", "click 1004 SF"]);
});

test("an earlier step's save notice is not the next step's: its error fails it, never a set (#288)", async () => {
  // The second save errors two looks after its click, the first step's notice showing until then.
  let dom = swapDom({ answer: ["saved", "error"], after: 2 });
  let got = await live(dom, [swap(1011, "BN", "SF", 1004, 0), swap(1004, "BN", "Util", 1009, 0)]);
  assert.equal(got.outcome, "failed");
  assert.deepEqual(got.steps.map((s) => [s.outcome, s.reason, s.message]), [
    ["set", null, SAVED_WORDS],
    ["failed", "Yahoo did not save the swap", "There was an error saving your changes."],
  ]);
  // The same notice rewritten in place: the error still reads as the second step's.
  dom = swapDom({ answer: ["saved", "error"], after: 2, sameNotice: true });
  got = await live(dom, [swap(1011, "BN", "SF", 1004, 0), swap(1004, "BN", "Util", 1009, 0)]);
  assert.deepEqual(got.steps.map((s) => s.outcome), ["set", "failed"]);
  // Rewritten in place with the same words: set only after the whole save window with no error,
  // and the reason says so.
  dom = swapDom({ sameNotice: true });
  got = await live(dom, [swap(1011, "BN", "SF", 1004, 0), swap(1004, "BN", "Util", 1009, 0)]);
  assert.deepEqual(got.steps.map((s) => [s.outcome, s.reason]), [
    ["set", null],
    ["set", "the save notice did not change; no error in 1 s"],
  ]);
  assert.equal(got.outcome, "set");
});

test("STOP, the brake or the guard read before each change stops the run before it", async () => {
  const dom = swapDom();
  let calls = 0;
  let got = await live(dom, [swap(1011, "BN", "SF", 1004, 0), swap(1012, "BN", "Util", 1010, 1)], { stopNow: async () => (++calls === 2 ? "STOP came on" : null) });
  assert.deepEqual([got.outcome, got.reason], ["stopped", "STOP came on (1 of 2 changes set first)"]);
  assert.deepEqual(got.steps.map((s) => [s.outcome, s.reason]), [["set", null], ["skipped", "STOP came on"]]);
  assert.equal(calls, 2);
  // Read before the first change too: nothing clicked.
  const fresh = swapDom();
  got = await live(fresh, [swap(1011, "BN", "SF", 1004, 0)], { stopNow: async () => "live refused: STOP is on (data/autopilot/STOP)" });
  assert.deepEqual([got.outcome, fresh.touched], ["stopped", []]);
});

test("a cleared held player goes to an empty bench row first; with none open he is the moves queue's", async () => {
  let dom = swapDom({ drop: ["1012"], empty: ["BN"] });
  let got = await live(dom, [swap(1011, "BN", "SF", 1004, 0)], { returns: [{ player: 1013, slot: "IL", status: null, tip: null }] });
  assert.equal(got.outcome, "set");
  assert.deepEqual(got.steps.map((s) => [s.player, s.kind, s.from_slot, s.to_slot, s.outcome]), [[1013, "return", "IL", "BN", "set"], [1011, "swap", "BN", "SF", "set"]]);
  assert.deepEqual(dom.touched.slice(0, 2), ["click 1013 IL", "click empty BN"]);
  assert.equal(got.after["1013"], "BN");
  dom = swapDom();
  got = await live(dom, [], { returns: [{ player: 1013, slot: "IL", status: null, tip: null }] });
  assert.deepEqual([got.outcome, got.reason, dom.touched], ["skipped", X.NEEDS_DROP, []]);
});

test("the live run's log: what it set, the lineup after, the moved players off their target and Yahoo's words", async () => {
  const c = X.readControls(form());
  const steps = stepsFor(c, [swap(1011, "BN", "SF", 1004, 0), swap(1012, "BN", "Util", 1010, 1)], {
    mode: "live",
    live: { ok: true, reason: null },
    target: { 1011: "SF", 1004: "BN", 1012: "Util", 1010: "BN" },
  });
  const dom = swapDom({ lockAfter: [1012] });
  const result = await live(dom, steps.steps);
  const run = X.liveRun({ steps, trigger: "routine_late", page: "/p", controls: c, checked: X.checkSteps(c, steps.steps, SLOTS), result, afterStartActive: true, extension: "0.11.0" });
  assert.deepEqual([run.mode, run.trigger, run.outcome, run.after_start_active], ["live", "routine_late", "set", true]);
  assert.deepEqual(run.diff, { 1012: "BN", 1010: "Util" });
  assert.equal(run.message, SAVED_WORDS);
  assert.deepEqual(run.before, c.lineup);
  assert.ok(!run.steps.some((s) => s.outcome === "would_set"));
  assert.ok(!keys(run).some((k) => /crumb/i.test(k)));
  assert.match(X.stripText({ steps, run, at: Date.now() }), /^live · 1 swap set \d\d:\d\d \(1 of 2 changes set; player 1012's game began \(his slot is fixed\)\)$/);
  // The mode: live only where the league is live and its guard holds now.
  assert.deepEqual(X.lineupMode(steps), { mode: "live", refused: null });
  assert.deepEqual(X.lineupMode({ ...steps, live: { ok: false, reason: "STOP is on (data/autopilot/STOP)" } }), { mode: "dry_run", refused: "live refused: STOP is on (data/autopilot/STOP)" });
  assert.deepEqual(X.lineupMode({ ...steps, live: null }), { mode: "dry_run", refused: "live refused: the guard did not answer" });
  assert.deepEqual(X.lineupMode({ ...steps, mode: "dry_run" }), { mode: "dry_run", refused: null });
  const late = X.unreadLineup({ day: DAY, trigger: "routine", page: "/p", read_at: "x" }, "0.11.0");
  assert.deepEqual([late.mode, late.outcome, late.reason], ["live", "failed", "clicked; Yahoo's answer was not read"]);
});

test("the lineup waits for a Start Active press due today, and never runs on a page read before one", () => {
  const row = { league: LEAGUE, need: true, mode: "live", live: { ok: true, reason: null } };
  const at = POSTED;
  assert.equal(X.startActiveWait(row, null, DAY, at), "Start Active Players is due in this league first: the lineup waits for its press");
  assert.equal(X.startActiveWait(row, { day: DAY, logged: false, at: at - 1 }, DAY, at), "Start Active Players is due in this league first: the lineup waits for its press");
  assert.equal(X.startActiveWait(row, { day: DAY, logged: true, at: at - 1 }, DAY, at), null);
  assert.equal(X.startActiveWait(row, { day: DAY, logged: true, at: at + 1 }, DAY, at), "Start Active Players pressed after this page was read: the next pass reads it again");
  assert.equal(X.startActiveWait({ ...row, need: false }, null, DAY, at), null);
  assert.equal(X.startActiveWait({ ...row, mode: "dry_run" }, null, DAY, at), null);
  assert.equal(X.startActiveWait({ ...row, live: { ok: false } }, null, DAY, at), null);
  assert.equal(X.startActiveWait(null, null, DAY, at), null);
});

test("swapStep's clicks: the player's label, the target's, and the cancel; no field, no submit, no fetch", () => {
  const src = X.swapStep.toString();
  assert.equal(src.match(/\.click\(\)/g).length, 3, "the player's label, the target's label and the cancel");
  assert.ok(!/\.(value|checked|selectedIndex|selected)\s*=[^=]|dispatchEvent|submit\(|fetch\(|XMLHttpRequest|crumb|roster-edit-form|select/.test(src));
  assert.ok(!/\.click\(/.test(X.setLineup.toString()));
  assert.ok(!/\bfetch\(|XMLHttpRequest|DOMParser/.test(fs.readFileSync(path.join(DIR, "lib/lineup.js"), "utf8")));
});

test("the worker puts a live run on record once per pass, keeps its run until the API has it and releases one that clicked nothing", async () => {
  const local = new Map();
  const w = loadWorker((f) => (f.method === "POST" ? [200, { at: "x" }] : [200, {}]), local);
  const record = { day: DAY, trigger: "routine", page: "/p", read_at: "x" };
  assert.equal((await w.send({ op: "lineup_setting", league: LEAGUE, record })).ok, true);
  let again = await w.send({ op: "lineup_setting", league: LEAGUE, record });
  assert.deepEqual([again.ok, again.error], [false, "a live run in this league awaits its log"]);
  const run = { day: DAY, mode: "live", trigger: "routine", outcome: "set", steps: [{ outcome: "set" }] };
  assert.equal((await w.send({ op: "lineup_log", league: LEAGUE, run, clicked: true })).ok, true);
  const kept = (await w.send({ op: "lineup_record", league: LEAGUE })).data;
  assert.deepEqual([kept.logged, kept.run.outcome, kept.trigger], [true, "set", "routine"]);
  assert.equal(w.store.get(`lineup:${LEAGUE}`).moves, 1);
  again = await w.send({ op: "lineup_setting", league: LEAGUE, record });
  assert.deepEqual([again.ok, again.error], [false, "this pass set the lineup already today"]);
  // The late pass runs; one that clicked nothing gives the record back.
  const lateRecord = { ...record, trigger: "routine_late" };
  assert.equal((await w.send({ op: "lineup_setting", league: LEAGUE, record: lateRecord })).ok, true);
  await w.send({ op: "lineup_log", league: LEAGUE, run: { ...run, trigger: "routine_late", outcome: "skipped", steps: [] }, release: true });
  assert.equal((await w.send({ op: "lineup_record", league: LEAGUE })).data.trigger, "routine");
});

/** The worker's answers in a live league whose guard holds: no Start Active due, no run on record. */
const liveWorker =
  ({ steps = {}, sa = [], press = null, put = { ok: true, data: { kept: true } } } = {}) =>
  (msg, sent) => {
    if (msg.op === "lineup_steps") {
      const r = worker({ mode: "live", live: { ok: true, reason: null }, target: { 1011: "SF", 1004: "BN" }, ...steps })(msg, sent);
      return r;
    }
    if (msg.op === "start_active_due") return { ok: true, data: { date: DAY, leagues: sa } };
    if (msg.op === "start_active_record") return { ok: true, data: press };
    if (msg.op === "lineup_record") return { ok: true, data: null };
    if (msg.op === "lineup_setting") return put;
    return worker()(msg, sent);
  };

test("in a live league whose guard holds, the routine's link sets the steps once on record and logs a live run", async () => {
  const roster = swapDom({ after: 0 });
  const v = await visitPage({ hash: "#pickandroll-lineup", answer: liveWorker(), swap: roster });
  assert.deepEqual(
    v.sent.map((m) => m.op),
    [
      ...["season_page", "settings", "lineup_steps", "start_active_due", "start_active_record", "lineup_record", "lineup_setting", "settings", "lineup_steps", "lineup_log"],
      // A swap set: Start Active's due read (#289); no league of it is this one, so the tab stays.
      "start_active_due",
    ],
  );
  assert.deepEqual(roster.touched, ["click 1011 BN", "click 1004 SF"]);
  const setting = v.sent[6].record;
  assert.deepEqual([setting.day, setting.mode, setting.trigger, setting.page, setting.extension], [DAY, "live", "routine", `/nba/${LEAGUE}/${TEAM}?date=${DAY}`, "0.6.0"]);
  // The guard read again from the API before the first click.
  assert.deepEqual(v.sent.slice(7, 9).map((m) => m.op), ["settings", "lineup_steps"]);
  const log = v.sent[9];
  assert.deepEqual([log.run.mode, log.run.outcome, log.run.after_start_active, log.clicked, log.release], ["live", "set", false, true, false]);
  assert.deepEqual(log.run.diff, {});
  assert.equal(log.run.message, SAVED_WORDS);
  assert.match(v.strip.textContent, /^pickandroll lineup: live · 1 swap set \d\d:\d\d$/);
});

test("a live run that set a later day's swap reads the set day settled and goes to today's page for the press (#289)", async () => {
  // The page sets tomorrow's lineup: the due's day is the one before, its row today's page.
  const today = "2026-10-23";
  const todayPage = `https://basketball.fantasysports.yahoo.com/nba/${LEAGUE}/${TEAM}?date=${today}`;
  const row = { league: LEAGUE, team: TEAM, need: true, reasons: ["lineup_set"], mode: "live", live: { ok: true, reason: null }, page: todayPage };
  const press = { day: today, logged: true, at: 0 };
  const answer =
    ({ date = today, sa = row, stop = false } = {}) =>
    (msg, sent) => {
      if (msg.op === "after_lineup_put") return { ok: true, data: { kept: true } };
      if (msg.op === "start_active_due") return { ok: true, data: { date, stop, leagues: [sa] } };
      return liveWorker({ sa: [row], press: { ...press, day: date } })(msg, sent);
    };
  // A swap Yahoo keeps open past its save: the set day's read waits it out.
  const roster = swapDom({ after: 0, linger: 3 });
  const v = await visitPage({ hash: "#pickandroll-lineup", answer: answer(), swap: roster });
  const put = v.sent.find((m) => m.op === "after_lineup_put");
  assert.deepEqual(put.handoff, { set_day: DAY, diff: {} });
  assert.deepEqual(v.assigned, [`${todayPage}#pickandroll-start-active-after-lineup`]);
  assert.ok(!v.sent.some((m) => m.op === "start_active_pressing"), "nothing pressed on the set day's page");
  assert.match(v.strip.textContent, /Start Active from today's page$/);
  assert.deepEqual(roster.touched, ["click 1011 BN", "click 1004 SF"]);
  // A run that set nothing, a set of today, a league not due, STOP: the tab stays.
  for (const [over, swap] of [
    [{}, swapDom({ answer: null })],
    [{ date: DAY }, swapDom({ after: 0 })],
    [{ sa: { ...row, need: false } }, swapDom({ after: 0 })],
    [{ stop: true }, swapDom({ after: 0 })],
  ]) {
    const w = await visitPage({ hash: "#pickandroll-lineup", answer: answer(over), swap });
    assert.deepEqual([w.assigned, w.sent.some((m) => m.op === "after_lineup_put")], [[], false]);
  }
});

test("live, a run waits for the day's Start Active press, refuses a pass already on record and runs dry where the guard refuses", async () => {
  const row = { league: LEAGUE, need: true, mode: "live", live: { ok: true, reason: null } };
  let roster = swapDom({ after: 0 });
  let v = await visitPage({ hash: "#pickandroll-lineup", answer: liveWorker({ sa: [row] }), swap: roster });
  let log = v.sent.find((m) => m.op === "lineup_log");
  assert.deepEqual([log.run.mode, log.run.outcome, log.run.reason, log.clicked], ["live", "skipped", "Start Active Players is due in this league first: the lineup waits for its press", false]);
  assert.ok(!v.sent.some((m) => m.op === "lineup_setting"));
  assert.deepEqual(roster.touched, []);
  // Pressed and logged before the page's read: the run goes on and says so.
  roster = swapDom({ after: 0 });
  v = await visitPage({ hash: "#pickandroll-lineup", answer: liveWorker({ sa: [row], press: { day: DAY, logged: true, at: 0 } }), swap: roster });
  log = v.sent.find((m) => m.op === "lineup_log");
  assert.deepEqual([log.run.outcome, log.run.after_start_active], ["set", true]);
  // The same pass again: nothing clicked.
  roster = swapDom({ after: 0 });
  v = await visitPage({ hash: "#pickandroll-lineup", answer: liveWorker({ put: { ok: false, error: "this pass set the lineup already today" } }), swap: roster });
  log = v.sent.find((m) => m.op === "lineup_log");
  assert.deepEqual([log.run.outcome, log.run.reason], ["skipped", "the run could not be put on record: this pass set the lineup already today"]);
  assert.deepEqual(roster.touched, []);
  // The guard refuses now: a dry run, nothing clicked.
  roster = swapDom({ after: 0 });
  v = await visitPage({ hash: "#pickandroll-lineup", answer: liveWorker({ steps: { live: { ok: false, reason: "STOP is on (data/autopilot/STOP)" } } }), swap: roster });
  log = v.sent.find((m) => m.op === "lineup_log");
  assert.deepEqual([log.run.mode, log.run.outcome, log.run.reason], ["dry_run", "would_set", "live refused: STOP is on (data/autopilot/STOP)"]);
  assert.deepEqual(roster.touched, []);
  // No tip-offs read for the day: nothing set.
  roster = swapDom({ after: 0 });
  v = await visitPage({ hash: "#pickandroll-lineup", answer: liveWorker({ steps: { tips: false } }), swap: roster });
  log = v.sent.find((m) => m.op === "lineup_log");
  assert.deepEqual([log.run.mode, log.run.outcome], ["live", "skipped"]);
  assert.deepEqual(roster.touched, []);
  // A plain visit in a live league clicks nothing.
  roster = swapDom({ after: 0 });
  v = await visitPage({ answer: liveWorker(), swap: roster });
  assert.ok(!v.sent.some((m) => m.op === "lineup_log"));
  assert.deepEqual(roster.touched, []);
});

test("the guard flips to refused between the visit's steps and its first click: nothing is clicked", async () => {
  const roster = swapDom({ after: 0 });
  const flips = (msg, sent) => {
    if (msg.op === "lineup_steps" && sent.filter((m) => m.op === "lineup_steps").length > 1) {
      return liveWorker({ steps: { live: { ok: false, reason: "a dry run on 30 days first: 9 so far" } } })(msg, sent);
    }
    return liveWorker()(msg, sent);
  };
  const v = await visitPage({ hash: "#pickandroll-lineup", answer: flips, swap: roster });
  assert.deepEqual(roster.touched, []);
  const log = v.sent.find((m) => m.op === "lineup_log");
  assert.deepEqual([log.run.mode, log.run.outcome, log.clicked, log.release], ["live", "stopped", false, true]);
  assert.equal(log.run.reason, "live refused: a dry run on 30 days first: 9 so far (0 of 1 change set first)");
  assert.deepEqual(log.run.steps.map((s) => s.outcome), ["skipped"]);
});
