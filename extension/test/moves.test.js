// node --test extension/test/*.test.js
// The moves executor's dry run (#171): the add page's controls read, every due entry's checks on
// them, the pass the log takes and the strip. Fixtures carry Yahoo ids, slot codes and dollar
// figures only.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const X = require("../lib/moves.js");

const LEAGUE = "100001";
const TEAM = 4;
const DAY = "2026-10-24";
const CLEARS = "2026-10-26";
const ROSTER = [2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009, 2010, 2011];

const hidden = (name, value) => ({ name, tag: "input", type: "hidden", value, checked: false });

/** An add page as the content script extracts it: the crumb taken out before the read. */
function rawPage({ add = 3001, drops = ROSTER, budget = 100, waiver = "Oct 26", submit = X.SUBMIT, form = true, path = null, message = null, noMoves = false } = {}) {
  return {
    path: path || X.addPath(LEAGUE, add),
    heading: "Claim Player From Waivers",
    token: form,
    form: form
      ? {
          action: `/nba/${LEAGUE}/${TEAM}/addplayer`,
          method: "post",
          fields: [
            hidden("stage", "2"),
            hidden("stat1", "P"),
            hidden("stat2", "P"),
            hidden("apid", String(add)),
            ...drops.map((k) => ({ name: "dpid", tag: "input", type: "checkbox", value: String(k), checked: false })),
            { name: "faab", tag: "input", type: "text", value: "0", checked: false },
            // Parsed without script, the noscript's submit is one of the form's elements.
            { name: X.SUBMIT, tag: "input", type: "submit", value: "Create claim", checked: false },
          ],
        }
      : null,
    submit: form ? submit : null,
    panel: `Your Bid $ Your Budget $${budget}${waiver ? ` Waiver Date ${waiver}` : ""}`,
    hint: `Must be between $0 and $${budget}`,
    cantcut: 2,
    no_moves: noMoves,
    message,
  };
}

const entry = (over = {}) => ({
  id: `${DAY}:${LEAGUE}:3001:2005`,
  league: LEAGUE,
  add: 3001,
  drop: 2005,
  from: CLEARS,
  availability: "W",
  queued: true,
  struck: false,
  bid: 3,
  bid_placed: 3,
  ...over,
});

const due = (over = {}) => ({
  league: LEAGUE,
  team: TEAM,
  date: DAY,
  mode: "dry_run",
  stop: false,
  reason: null,
  entries: [entry()],
  protected: { 2001: "kept: beats the best add" },
  pending: [],
  cap: 2,
  done: 0,
  adds_left: [{ start: "2026-10-20", end: "2026-10-26", adds: 4 }],
  budget: 100,
  ...over,
});

test("the fragments that start a pass; any other is a plain visit", () => {
  assert.equal(X.movesTriggerOf("#pickandroll-moves"), "routine");
  assert.equal(X.movesTriggerOf("#pickandroll-moves-late"), "routine_late");
  assert.equal(X.movesTriggerOf("#pickandroll-lineup"), null);
  assert.equal(X.movesTriggerOf(""), null);
  assert.equal(X.addPath(LEAGUE, 3001), `/nba/${LEAGUE}/addplayer?apid=3001`);
});

test("the add page's controls as the DOM read on #171 found them", () => {
  const p = X.readAddPage(rawPage(), CLEARS);
  assert.equal(p.action, `/nba/${LEAGUE}/${TEAM}/addplayer`);
  assert.equal(p.method, "post");
  assert.equal(p.add, 3001);
  assert.equal(p.stage, "2");
  assert.deepEqual(p.drops, ROSTER);
  assert.deepEqual([p.bid, p.budget, p.bid_max, p.waiver_date], [true, 100, 100, CLEARS]);
  assert.deepEqual([p.submit, p.token, p.cantcut, p.no_moves], [X.SUBMIT, true, 2, false]);
  assert.deepEqual(p.fields, ["stage", "stat1", "stat2", "apid", "dpid", "faab", X.SUBMIT]);
});

test("the page's waiver date takes the year nearest the clear date", () => {
  assert.equal(X.pageDay("Oct 26", "2026-10-26"), "2026-10-26");
  assert.equal(X.pageDay("Jan 2", "2026-12-30"), "2027-01-02");
  assert.equal(X.pageDay("Dec 31", "2027-01-01"), "2026-12-31");
  assert.equal(X.pageDay("soon", "2026-10-26"), null);
});

test("every check passes: the claim it would place, with the form as it would fill it", () => {
  const e = entry();
  const page = X.readAddPage(rawPage(), e.from);
  assert.equal(X.entryProblem(e, due(), []), null);
  const check = X.pageCheck(e, page, due());
  assert.deepEqual(check, { outcome: "would_claim", reason: null });
  const line = X.moveCheck(e, check, page);
  assert.deepEqual([line.id, line.add, line.drop, line.bid, line.outcome, line.page], [e.id, 3001, 2005, 3, "would_claim", X.addPath(LEAGUE, 3001)]);
  assert.deepEqual(line.controls.would_fill, { apid: 3001, dpid: 2005, faab: 3, submit: X.SUBMIT });
  // Field names only, never the crumb: the log refuses any key naming it.
  const keys = JSON.stringify(line).match(/"[^"]+":/g).map((k) => k.slice(1, -2));
  assert.ok(!keys.some((k) => /crumb/i.test(k)));
});

test("a struck bid is a $0 claim", () => {
  const e = entry({ bid_placed: 0 });
  const page = X.readAddPage(rawPage(), e.from);
  assert.equal(X.pageCheck(e, page, due()).outcome, "would_claim");
  assert.equal(X.moveCheck(e, { outcome: "would_claim" }, page).controls.would_fill.faab, 0);
});

test("the checks before any page: struck, open spot, protected, pending, the pass's own claims, the cap and the week's adds", () => {
  const d = due();
  assert.equal(X.entryProblem(entry({ struck: true }), d, []), "struck: it is never executed");
  assert.equal(X.entryProblem(entry({ drop: null }), d, []), "an open-spot claim is not read yet");
  assert.equal(X.entryProblem(entry({ drop: 2001 }), d, []), "the drop is protected (kept: beats the best add)");
  assert.equal(X.entryProblem(entry(), due({ pending: [{ id: "x", add: 3001, drop: 2009 }] }), []), "a claim on the add is pending");
  assert.equal(X.entryProblem(entry(), d, [entry({ id: "y", drop: 2006 })]), "this pass claims the add already");
  assert.equal(X.entryProblem(entry(), d, [entry({ id: "y", add: 3002 })]), "this pass drops that player already");
  assert.equal(X.entryProblem(entry(), due({ done: 1 }), [entry({ id: "y", add: 3002, drop: 2006 })]), "over the day's cap");
  const tight = due({ cap: 3, adds_left: [{ start: "2026-10-20", end: "2026-10-26", adds: 1 }] });
  assert.equal(X.entryProblem(entry(), tight, [entry({ id: "y", add: 3002, drop: 2006 })]), "no adds left this week");
  // A claim clearing in the next week does not use this week's adds.
  const next = due({ cap: 3, adds_left: [{ start: "2026-10-20", end: "2026-10-26", adds: 1 }, { start: "2026-10-27", end: "2026-11-02", adds: 4 }] });
  assert.equal(X.entryProblem(entry({ from: "2026-10-27" }), next, [entry({ id: "y", add: 3002, drop: 2006 })]), null);
});

test("the page's checks: what the page shows against the entry", () => {
  const e = entry();
  const check = (raw, d = due(), x = e) => X.pageCheck(x, X.readAddPage(raw, x.from), d);
  assert.deepEqual(check(rawPage({ path: `/nba/${LEAGUE}/players` })), { outcome: "skipped", reason: `the add page answered /nba/${LEAGUE}/players` });
  assert.deepEqual(check(rawPage({ path: `/nba/${LEAGUE}/addplayer?apid=3002` })).outcome, "skipped");
  // Yahoo may add its own parameters to the add page's address.
  assert.equal(check(rawPage({ path: `${X.addPath(LEAGUE, 3001)}&stat1=P` })).outcome, "would_claim");
  assert.deepEqual(check(rawPage({ form: false })), { outcome: "skipped", reason: "the add page has no claim form" });
  assert.deepEqual(check(rawPage({ form: false, message: "This player is no longer available." })), { outcome: "gone", reason: "This player is no longer available." });
  assert.equal(check(rawPage(), due({ team: 9 })).reason, "the form is not my team's claim");
  assert.equal(check(rawPage({ add: 3009, path: X.addPath(LEAGUE, 3001) })).reason, "the page claims another player than the entry");
  assert.equal(check(rawPage({ waiver: null })).reason, "the page shows no waiver date: the add is not on waivers");
  assert.equal(check(rawPage({ waiver: "Oct 27" })).reason, "the page's waiver date is 2026-10-27, the queue's 2026-10-26");
  assert.equal(check(rawPage(), due(), entry({ availability: "FA" })).reason, "a free-agent add is not read yet");
  assert.equal(check(rawPage({ drops: ROSTER.filter((k) => k !== 2005) })).reason, "the drop has no control on the page (not on my roster, or on Yahoo's can't-cut list)");
  assert.equal(check(rawPage({ noMoves: true })).reason, "Yahoo shows no moves left");
  assert.equal(check(rawPage({ budget: 2 })).reason, "the bid ($3) is over the $2 left");
  assert.equal(check(rawPage({ submit: null })).reason, "the page has no claim submit");
});

test("the pass the log takes: would claim, skipped, nothing due, stopped and failed", () => {
  const e = entry();
  const page = X.readAddPage(rawPage(), e.from);
  const ok = X.moveCheck(e, X.pageCheck(e, page, due()), page);
  const skipped = X.moveCheck(entry({ id: "y", drop: 2001 }), { outcome: "skipped", reason: "the drop is protected (kept)" });
  let run = X.movesPass({ due: due(), trigger: "routine", checks: [ok, skipped], extension: "0.7.0" });
  assert.deepEqual([run.day, run.mode, run.trigger, run.outcome, run.reason, run.extension], [DAY, "dry_run", "routine", "would_claim", null, "0.7.0"]);
  assert.equal(run.entries.length, 2);
  assert.equal(run.entries[1].controls, null);
  run = X.movesPass({ due: due(), trigger: "panel", checks: [skipped] });
  assert.deepEqual([run.outcome, run.reason], ["skipped", "every due entry failed a check"]);
  run = X.movesPass({ due: due({ entries: [], reason: "nothing due now" }), trigger: "routine" });
  assert.deepEqual([run.outcome, run.reason, run.entries], ["nothing_due", "nothing due now", []]);
  run = X.movesPass({ due: due({ stop: true, entries: [] }), trigger: "routine" });
  assert.deepEqual([run.outcome, run.reason], ["stopped", "STOP is on (data/autopilot/STOP)"]);
  run = X.movesPass({ due: due(), trigger: "routine", error: "not signed in to Yahoo" });
  assert.deepEqual([run.outcome, run.reason], ["failed", "not signed in to Yahoo"]);
});

test("the strip and the panel's line", () => {
  const at = new Date(2026, 9, 24, 9, 2).getTime();
  assert.equal(X.movesStripText({ browserOff: true }), "off in this browser (the extension's settings)");
  assert.equal(X.movesStripText({ due: due({ mode: "off" }) }), "off in this league");
  assert.equal(X.movesStripText({ due: due({ stop: true }) }), "STOP is on: nothing runs");
  assert.equal(X.movesStripText({ due: due({ entries: [], reason: "nothing due now" }) }), "dry run · nothing due now");
  const e = entry();
  const page = X.readAddPage(rawPage(), e.from);
  const run = X.movesPass({ due: due(), trigger: "routine", checks: [X.moveCheck(e, X.pageCheck(e, page, due()), page)] });
  assert.equal(X.movesStripText({ due: due(), run, at }), "dry run · 1 claim logged 09:02");
  const last = { day: DAY, trigger: "routine", outcome: "would_claim", reason: null, claims: 2 };
  assert.equal(X.movesLastText(last, "3 min ago"), `${DAY} · routine: would claim 2, 3 min ago`);
  assert.equal(X.movesLastText(null, ""), "no pass from this browser yet");
});

test("the library toggles no drop, sets no bid and submits nothing", () => {
  const src = require("node:fs").readFileSync(require("node:path").join(__dirname, "..", "lib", "moves.js"), "utf8");
  assert.ok(!/\.click\(|dispatchEvent|submit\(|requestSubmit|fetch\(/.test(src));
  assert.ok(!/\.(value|selectedIndex|checked)\s*=[^=]/.test(src));
});

// ---------------------------------------------------------------- the content script's pass
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const DIR = path.join(__dirname, "..");
const SITE = "https://basketball.fantasysports.yahoo.com";

/** A fake element: its text, attributes and children by selector. */
const el = (props = {}) => ({ textContent: "", getAttribute: (a) => (props.attrs || {})[a] ?? null, querySelectorAll: () => [], querySelector: () => null, ...props });

/** An add page parsed, as the fake DOMParser gives it: the form and controls the DOM read found. */
function addDoc({ add = 3001, drops = ROSTER, budget = 100, waiver = "Oct 26" } = {}) {
  const removed = new Set();
  const crumb = { name: "crumb", tagName: "INPUT", type: "hidden", value: "SECRET-TOKEN", remove: () => removed.add(crumb) };
  const input = (name, type, value) => ({ name, tagName: "INPUT", type, value, checked: false });
  const all = [
    input("stage", "hidden", "2"),
    crumb,
    input("stat1", "hidden", "P"),
    input("stat2", "hidden", "P"),
    input("apid", "hidden", String(add)),
    ...drops.map((k) => input("dpid", "checkbox", String(k))),
    input("faab", "text", "0"),
    input(X.SUBMIT, "submit", "Create claim"),
  ];
  const hint = el({ textContent: ` Must be between $0 and $${budget} ` });
  const form = el({
    attrs: { action: `/nba/${LEAGUE}/${TEAM}/addplayer`, method: "post" },
    querySelectorAll: (sel) => (sel === "p, span, div" ? [hint] : sel.startsWith(".T-action-icon-cantcut") ? [el(), el()] : []),
  });
  // Live, as a form's elements are: an input taken out is gone from them.
  Object.defineProperty(form, "elements", { get: () => all.filter((x) => !removed.has(x)) });
  return {
    removed,
    querySelectorAll: (sel) => (sel.includes("crumb") ? [crumb].filter((x) => !removed.has(x)) : sel === "h1, h2, h3" ? [el({ textContent: "Claim Player From Waivers" })] : []),
    querySelector: (sel) => (sel === "form#add-drop-players-form" ? form : sel === "#submit-add-drop-button" ? el({ attrs: { name: X.SUBMIT } }) : null),
    getElementById: (id) => (id === "faab-bid-fieldset" ? el({ textContent: `Your Bid $ Your Budget $${budget} Waiver Date ${waiver}` }) : id === "add-drop-submit-container" ? el() : null),
  };
}

/** league.js on my team page (``hash`` its fragment): a chrome whose worker answers each op with
 * ``answer``, a fetch whose add pages ``pages`` gives (by apid; a function throws), and the
 * DOMParser that reads them. Returns the messages, the GETs, the strips and the URL replaced. */
async function visitMoves({ hash = "#pickandroll-moves", answer, pages = {}, team = TEAM }) {
  const nodes = {};
  const doc = {
    querySelector: () => null,
    querySelectorAll: () => [],
    getElementById: (id) => nodes[id] || null,
    createElement: () => ({ style: {}, setAttribute() {}, textContent: "" }),
    documentElement: {
      cloneNode: () => ({ querySelectorAll: () => [], outerHTML: "<html></html>" }),
      append: (e) => {
        nodes[e.id] = e;
      },
    },
  };
  const url = new URL(`${SITE}/nba/${LEAGUE}/${team}${hash}`);
  const location = { href: url.href, hash: url.hash, pathname: url.pathname, search: url.search, origin: url.origin, assign() {} };
  const sent = [];
  const gets = [];
  const parsed = [];
  const replaced = [];
  const listeners = [];
  const delays = [];
  const timers = [];
  const chrome = {
    runtime: {
      connect: () => ({}),
      getManifest: () => ({ version: "0.7.0" }),
      onMessage: { addListener: (fn) => listeners.push(fn) },
      sendMessage: async (msg) => {
        sent.push(JSON.parse(JSON.stringify(msg)));
        return answer(msg, sent);
      },
    },
  };
  async function fetch(p, opts = {}) {
    gets.push({ path: p, ...JSON.parse(JSON.stringify({ method: opts.method, body: opts.body, credentials: opts.credentials })) });
    const u = new URL(p, SITE);
    const page = pages[u.searchParams.get("apid")];
    if (typeof page === "function") page();
    return { ok: true, status: 200, url: u.href, text: async () => u.searchParams.get("apid") };
  }
  class DOMParser {
    parseFromString(apid) {
      const d = pages[apid] || addDoc({ add: Number(apid) });
      parsed.push(d);
      return d;
    }
  }
  const ctx = vm.createContext({
    chrome,
    location,
    document: doc,
    history: { replaceState: (_s, _t, u) => replaced.push(u) },
    setTimeout: (fn, ms) => {
      delays.push(ms);
      if (ms === 1500) timers.push(fn);
      else if (ms !== 20000) Promise.resolve().then(fn);
      return delays.length;
    },
    clearTimeout: () => {},
    AbortController,
    URL,
    URLSearchParams,
    Date,
    console,
    fetch,
    DOMParser,
  });
  ctx.window = ctx;
  ctx.globalThis = ctx;
  for (const file of ["lib/league.js", "lib/lineup.js", "lib/moves.js", "league.js"]) vm.runInContext(fs.readFileSync(path.join(DIR, file), "utf8"), ctx);
  for (const fn of timers.splice(0)) await fn();
  return { sent, gets, parsed, replaced, listeners, delays, strip: nodes["pickandroll-moves-strip"] };
}

/** The worker's answers: the post accepted, the due entries, the log taking the pass. */
const movesWorker =
  (over = {}, settings = {}) =>
  (msg) => {
    if (msg.op === "season_page") return { ok: true, data: { post: { accepted: ["roster/4"] }, follow: null } };
    if (msg.op === "settings") return { ok: true, data: { lineup_executor: "on", moves_executor: "on", ...settings } };
    if (msg.op === "moves_due") return { ok: true, data: due(over) };
    if (msg.op === "moves_log") return { ok: true, data: { at: "x" } };
    return { ok: false, error: `unexpected ${msg.op}` };
  };

const withPage = (e) => ({ ...e, page: X.addPath(LEAGUE, e.add) });
const ops = (v) => v.sent.map((m) => m.op);
const keysOf = (o) => (o && typeof o === "object" ? Object.entries(o).flatMap(([k, v]) => [k, ...keysOf(v)]) : []);

test("the routine's link reads each due entry's add page, one at a time, and logs the claims it would place", async () => {
  const entries = [withPage(entry({ id: "a", drop: 2001 })), withPage(entry({ id: "b" })), withPage(entry({ id: "c", add: 3002, drop: 2006, bid_placed: 0 }))];
  const v = await visitMoves({ answer: movesWorker({ entries, cap: 3 }) });
  assert.deepEqual(ops(v), ["season_page", "settings", "moves_due", "moves_log"]);
  // The protected drop never reaches its page; the other two are GETs with the page's own session.
  assert.deepEqual(v.gets, [
    { path: X.addPath(LEAGUE, 3001), credentials: "same-origin" },
    { path: X.addPath(LEAGUE, 3002), credentials: "same-origin" },
  ]);
  assert.ok(v.delays.includes(2000), "a pause between two add pages");
  // The crumb was taken out of every page before it was read.
  assert.ok(v.parsed.every((d) => d.removed.size === 1));
  const run = v.sent[3].run;
  assert.deepEqual([run.mode, run.trigger, run.outcome, run.extension], ["dry_run", "routine", "would_claim", "0.7.0"]);
  assert.deepEqual(run.entries.map((e) => [e.id, e.outcome]), [["a", "skipped"], ["b", "would_claim"], ["c", "would_claim"]]);
  assert.equal(run.entries[0].reason, "the drop is protected (kept: beats the best add)");
  assert.deepEqual(run.entries[2].controls.would_fill, { apid: 3002, dpid: 2006, faab: 0, submit: X.SUBMIT });
  assert.deepEqual(run.entries[1].controls.fields, ["stage", "stat1", "stat2", "apid", "dpid", "faab", X.SUBMIT]);
  assert.equal(run.entries[1].controls.token, true);
  assert.ok(!keysOf(run).some((k) => /crumb/i.test(k)) && !JSON.stringify(run).includes("SECRET-TOKEN"));
  assert.match(v.strip.textContent, /^pickandroll moves: dry run · 2 claims logged \d\d:\d\d$/);
  assert.deepEqual(v.replaced, [`/nba/${LEAGUE}/${TEAM}`]);
});

test("a plain visit or the lineup's link runs no moves pass", async () => {
  for (const hash of ["", "#pickandroll-lineup"]) {
    const v = await visitMoves({ hash, answer: movesWorker() });
    assert.ok(!ops(v).some((op) => op.startsWith("moves_")), hash);
    assert.deepEqual(v.gets, []);
  }
});

test("off in the league, the browser's brake, another team's page and STOP", async () => {
  let v = await visitMoves({ answer: movesWorker({ mode: "off", entries: [] }) });
  assert.ok(!ops(v).includes("moves_log"));
  assert.equal(v.strip.textContent, "pickandroll moves: off in this league");
  v = await visitMoves({ answer: movesWorker({}, { moves_executor: "off" }) });
  assert.deepEqual(ops(v), ["season_page", "settings"]);
  assert.equal(v.strip.textContent, "pickandroll moves: off in this browser (the extension's settings)");
  v = await visitMoves({ team: 9, answer: movesWorker() });
  assert.ok(!ops(v).includes("moves_log"));
  v = await visitMoves({ answer: movesWorker({ stop: true, entries: [] }) });
  assert.equal(v.sent[3].run.outcome, "stopped");
  assert.deepEqual(v.gets, []);
});

test("an add page that cannot be read stops the pass: the rest are not read", async () => {
  const entries = [withPage(entry({ id: "b" })), withPage(entry({ id: "c", add: 3002, drop: 2006 }))];
  const pages = {
    3001: () => {
      throw new Error("Failed to fetch");
    },
  };
  const v = await visitMoves({ answer: movesWorker({ entries }), pages });
  assert.equal(v.gets.length, 1);
  const run = v.sent.find((m) => m.op === "moves_log").run;
  assert.deepEqual([run.outcome, run.reason], ["failed", "the add page could not be read: Failed to fetch"]);
  assert.deepEqual(run.entries.map((e) => [e.id, e.outcome]), [["b", "failed"], ["c", "skipped"]]);
  assert.equal(run.entries[1].reason, "the pass stopped at an add page it could not read");
});

test("the side panel's button runs a pass from a fresh post of the page", async () => {
  const v = await visitMoves({ hash: "", answer: movesWorker({ entries: [withPage(entry())] }) });
  const reply = await new Promise((resolve) => {
    for (const fn of v.listeners) if (fn({ op: "moves_run" }, {}, resolve) === true) return;
  });
  assert.equal(reply.ok, true);
  assert.deepEqual([reply.data.pass.trigger, reply.data.pass.outcome], ["panel", "would_claim"]);
  assert.deepEqual(ops(v), ["season_page", "season_page", "settings", "moves_due", "moves_log"]);
});
