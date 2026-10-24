// node --test extension/test/*.test.js
// The moves executor's dry run (#171): the add page's controls read, a due entry's checks on them,
// the pass the log takes, the strip, the panel's links, and the content script on an add page
// opened with the routine's fragment. Fixtures carry Yahoo ids, slot codes and dollar figures only.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const X = require("../lib/moves.js");

const DIR = path.join(__dirname, "..");
const SITE = "https://basketball.fantasysports.yahoo.com";
const LEAGUE = "100001";
const TEAM = 4;
const DAY = "2026-10-24";
const CLEARS = "2026-10-26";
const ADD = 3001;
const ROSTER = [2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013];
const CANTCUT = [2012, 2013];

const hidden = (name, value) => ({ name, tag: "input", type: "hidden", value, checked: false });
const ICON = { cantcut: "noactioncc-cantcut F-icon T-action-icon-cantcut", locked: "noactionl- F-icon T-action-icon-locked" };

/** An add page as the content script extracts it from the rendered page: the crumb's value never
 * read. ``markers`` puts an icon on a roster row, ``addClasses`` on the add's own row. */
function rawPage({ add = ADD, budget = 100, waiver = "Oct 26", heading = X.CLAIM_HEADING, form = true, markers = {}, addClasses = "noactionda- F-icon T-action-icon-disabled-add", action = `/nba/${LEAGUE}/${TEAM}/addplayer`, submit = X.SUBMIT, hint = true, message = null } = {}) {
  const cut = new Set([...CANTCUT, ...Object.keys(markers).map(Number)]);
  return {
    path: `/nba/${LEAGUE}/addplayer?apid=${add}`,
    heading,
    form: form
      ? {
          action,
          method: "post",
          fields: [
            hidden("stage", "2"),
            { name: "crumb", tag: "input", type: "hidden", value: null, checked: false },
            hidden("stat1", "P"),
            hidden("stat2", "P"),
            hidden("apid", String(add)),
            ...ROSTER.filter((k) => !cut.has(k)).map((k) => ({ name: "dpid", tag: "input", type: "checkbox", value: String(k), checked: false })),
            { name: "faab", tag: "input", type: "text", value: "0", checked: false },
          ],
        }
      : null,
    submit: form ? submit : null,
    panel: `Your Bid $ Your Budget $${budget}${waiver ? ` Waiver Date ${waiver}` : ""}`,
    hint: hint ? `Must be between $0 and $${budget}` : null,
    add_row: { id: String(add), classes: addClasses },
    rows: ROSTER.map((k) => ({ id: String(k), classes: CANTCUT.includes(k) ? ICON.cantcut : markers[k] ? ICON[markers[k]] : "" })),
    message,
  };
}

const entry = (over = {}) => ({
  id: `${DAY}:${LEAGUE}:${ADD}:2005`,
  league: LEAGUE,
  add: ADD,
  drop: 2005,
  from: CLEARS,
  availability: "W",
  queued: true,
  struck: false,
  bid: 3,
  bid_placed: 3,
  page: `/nba/${LEAGUE}/addplayer?apid=${ADD}`,
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

const READ_AT = "2026-10-24T16:00:08.000Z";
const checkOn = (raw, d = due(), e = entry()) => X.pageCheck(e, X.readAddPage(raw, e.from), d);

test("the fragments that start a pass and the add page they run on", () => {
  assert.equal(X.movesTriggerOf("#pickandroll-moves"), "routine");
  assert.equal(X.movesTriggerOf("#pickandroll-moves-late"), "routine_late");
  assert.equal(X.movesTriggerOf("#pickandroll-moves-panel"), "panel");
  assert.equal(X.movesTriggerOf("#pickandroll-lineup"), null);
  assert.equal(X.movesTriggerOf(""), null);
  assert.deepEqual(X.addPageOf(`${SITE}/nba/${LEAGUE}/addplayer?apid=${ADD}#pickandroll-moves`), { league: LEAGUE, add: ADD });
  assert.equal(X.addPageOf(`${SITE}/nba/${LEAGUE}/addplayer`), null);
  assert.equal(X.addPageOf(`${SITE}/nba/${LEAGUE}/${TEAM}`), null);
  assert.equal(X.addPageOf(`https://example.com/nba/${LEAGUE}/addplayer?apid=1`), null);
});

test("the add page's controls as the DOM read on #171 found them", () => {
  const p = X.readAddPage(rawPage(), CLEARS);
  assert.deepEqual([p.action, p.league, p.team, p.method, p.stage, p.add], [`/nba/${LEAGUE}/${TEAM}/addplayer`, LEAGUE, TEAM, "post", true, ADD]);
  assert.deepEqual(p.boxes, ROSTER.filter((k) => !CANTCUT.includes(k)));
  assert.deepEqual(p.cantcut, CANTCUT);
  assert.deepEqual(p.add_row, { id: ADD, markers: ["disabled_add"] });
  assert.deepEqual([p.bid, p.budget, p.bid_min, p.bid_max, p.waiver_date], [true, 100, 0, 100, CLEARS]);
  assert.deepEqual([p.submit, p.crumb, p.heading], [X.SUBMIT, true, X.CLAIM_HEADING]);
  assert.deepEqual(p.fields, ["stage", "crumb", "stat1", "stat2", "apid", "dpid", "faab"]);
});

test("the page's waiver date takes the year nearest the clear date", () => {
  assert.equal(X.pageDay("Oct 26", "2026-10-26"), "2026-10-26");
  assert.equal(X.pageDay("Jan 2", "2026-12-30"), "2027-01-02");
  assert.equal(X.pageDay("Dec 31", "2027-01-01"), "2026-12-31");
  assert.equal(X.pageDay("soon", "2026-10-26"), null);
});

test("every check passes: the claim it would place, one drop, with the form as it would fill it", () => {
  const e = entry();
  const page = X.readAddPage(rawPage(), e.from);
  assert.equal(X.entryProblem(e, due()), null);
  const check = X.pageCheck(e, page, due());
  assert.deepEqual(check, { outcome: "would_claim", reason: null });
  const line = X.moveCheck(e, check, page, due(), READ_AT);
  assert.deepEqual([line.id, line.add, line.drop, line.bid, line.outcome, line.page], [e.id, ADD, 2005, 3, "would_claim", e.page]);
  assert.deepEqual(line.controls.would_fill, { action: `/nba/${LEAGUE}/${TEAM}/addplayer`, apid: ADD, dpid: 2005, faab: 3, submit: X.SUBMIT });
  const c = line.controls;
  assert.deepEqual(c.fields, ["stage", "stat1", "stat2"]);
  assert.deepEqual([c.crumb, c.heading, c.waiver_date, c.budget, c.adds_left, c.read_at], ["present", X.CLAIM_HEADING, CLEARS, 100, 4, READ_AT]);
  assert.deepEqual([c.cantcut, c.add_markers, c.bid_range, c.drops], [CANTCUT, ["disabled_add"], [0, 100], 11]);
  // The only key naming the crumb says it was there, nothing more.
  const keys = (o) => (o && typeof o === "object" ? Object.entries(o).flatMap(([k, v]) => [[k, v], ...keys(v)]) : []);
  assert.deepEqual(keys(line).filter(([k]) => /crumb/i.test(k)), [["crumb", "present"]]);
});

test("a struck bid is a $0 claim", () => {
  const e = entry({ bid_placed: 0 });
  const page = X.readAddPage(rawPage(), e.from);
  assert.equal(X.pageCheck(e, page, due()).outcome, "would_claim");
  assert.equal(X.moveCheck(e, { outcome: "would_claim" }, page, due(), READ_AT).controls.would_fill.faab, 0);
});

test("the checks before the page: the state, struck, open spot, protected, pending, the cap and the week's adds", () => {
  assert.equal(X.entryProblem(entry(), due({ mode: "off" })), "the moves executor is off in this league");
  assert.equal(X.entryProblem(entry(), due({ stop: true })), "STOP is on (data/autopilot/STOP)");
  assert.equal(X.entryProblem(entry({ struck: true }), due()), "struck: it is never executed");
  assert.equal(X.entryProblem(entry({ queued: false }), due()), "not queued: it is never executed");
  assert.equal(X.entryProblem(entry({ drop: null }), due()), "an open-spot claim is not read yet");
  assert.equal(X.entryProblem(entry({ drop: 2001 }), due()), "the drop is protected (kept: beats the best add)");
  assert.equal(X.entryProblem(entry(), due({ pending: [{ id: "x", add: ADD, drop: 2009, from: CLEARS }] })), "a claim on the add is pending");
  assert.equal(X.entryProblem(entry(), due({ done: 2 })), "over the day's cap");
  assert.equal(X.entryProblem(entry(), due({ adds_left: [{ start: "2026-10-20", end: "2026-10-26", adds: 0 }] })), "no adds left this week");
  // A claim clearing in the next week does not need this week's adds.
  const next = due({ adds_left: [{ start: "2026-10-20", end: "2026-10-26", adds: 0 }, { start: "2026-10-27", end: "2026-11-02", adds: 4 }] });
  assert.equal(X.entryProblem(entry({ from: "2026-10-27" }), next), null);
  assert.equal(X.entryProblem(entry(), due({ mode: "live" })), null);
});

test("the page's checks: identity, the claim heading, waivers, the drop's marker, moves left, the bid and the submit", () => {
  const skipped = (raw, d, e) => checkOn(raw, d, e).reason;
  assert.deepEqual(checkOn(rawPage({ form: false })), { outcome: "skipped", reason: "page not read" });
  assert.equal(skipped(rawPage({ heading: "Add Player" })), 'the page\'s heading is "Add Player", not the claim\'s');
  assert.equal(skipped(rawPage({ action: `/nba/100002/${TEAM}/addplayer` })), "the form is not this league's claim");
  assert.equal(skipped(rawPage(), due({ team: 9 })), "the form is not my team's claim");
  assert.equal(skipped(rawPage({ add: 3009 })), "the page claims another player than the entry");
  assert.equal(skipped(rawPage({ waiver: null })), "the page shows no waiver date");
  assert.equal(skipped(rawPage({ waiver: "Oct 27" })), "the page's waiver date is 2026-10-27, the queue's 2026-10-26");
  assert.equal(skipped(rawPage(), due(), entry({ drop: 2012 })), "the drop 2012 cannot be picked (cantcut)");
  assert.equal(skipped(rawPage({ markers: { 2005: "locked" } })), "the drop 2005 cannot be picked (locked)");
  assert.equal(skipped(rawPage(), due(), entry({ drop: 2999 })), "the drop 2999 cannot be picked (none)");
  assert.equal(skipped(rawPage({ addClasses: "noactionna- F-icon T-action-icon-no-add" })), "Yahoo shows no more roster moves on the add");
  assert.equal(skipped(rawPage({ budget: 2 })), "the bid ($3) is outside the page's $0 to $2");
  assert.equal(skipped(rawPage(), due(), entry({ bid_placed: 2.5 })), "the bid (2.5) is not a whole dollar");
  assert.equal(skipped(rawPage({ hint: false })), "the page shows no bid range");
  assert.equal(skipped(rawPage({ submit: null })), "the page has no claim submit");
});

test("gone only when the page shows the add on a team; a page with no form is not read", () => {
  const onTeam = rawPage({ addClasses: "F-icon T-action-icon-trade" });
  assert.deepEqual(checkOn(onTeam), { outcome: "gone", reason: "the page shows the add on a team" });
  assert.equal(checkOn(rawPage({ form: false, message: "This player is owned by another team." })).outcome, "gone");
  assert.equal(checkOn(rawPage({ form: false, message: "Something went wrong." })).reason, "page not read");
});

test("the pass the log takes: would claim, skipped, gone and stopped", () => {
  const e = entry();
  const page = X.readAddPage(rawPage(), e.from);
  const line = (check) => X.moveCheck(e, check, page, due(), READ_AT);
  let run = X.movesPass({ due: due(), trigger: "routine", checks: [line(X.pageCheck(e, page, due()))], extension: "0.7.0" });
  assert.deepEqual([run.day, run.mode, run.trigger, run.outcome, run.reason, run.extension], [DAY, "dry_run", "routine", "would_claim", null, "0.7.0"]);
  run = X.movesPass({ due: due(), trigger: "routine_late", checks: [line({ outcome: "skipped", reason: "page not read" })] });
  assert.deepEqual([run.outcome, run.reason], ["skipped", "page not read"]);
  run = X.movesPass({ due: due(), trigger: "routine", checks: [line({ outcome: "gone", reason: "the page shows the add on a team" })] });
  assert.equal(run.outcome, "skipped");
  run = X.movesPass({ due: due({ stop: true, entries: [] }), trigger: "routine" });
  assert.deepEqual([run.outcome, run.reason, run.entries], ["stopped", "STOP is on (data/autopilot/STOP)", []]);
  // A live league still logs a dry run: this build claims nothing.
  run = X.movesPass({ due: due({ mode: "live" }), trigger: "panel", checks: [line({ outcome: "would_claim" })] });
  assert.equal(run.mode, "dry_run");
});

test("the strip, the panel's line and the panel's links", () => {
  const at = new Date(2026, 9, 24, 9, 2).getTime();
  assert.equal(X.movesStripText({ browserOff: true }), "off in this browser (the extension's settings)");
  assert.equal(X.movesStripText({ due: due({ mode: "off" }) }), "off in this league");
  assert.equal(X.movesStripText({ due: due({ stop: true }) }), "STOP is on: nothing runs");
  assert.equal(X.movesStripText({ due: due(), none: true }), "dry run · this player is not due in the queue: nothing logged");
  const e = entry();
  const page = X.readAddPage(rawPage(), e.from);
  const run = X.movesPass({ due: due(), trigger: "routine", checks: [X.moveCheck(e, X.pageCheck(e, page, due()), page, due(), READ_AT)] });
  assert.equal(X.movesStripText({ due: due(), run, at }), "dry run · would claim for $3, dropping 2005; logged 09:02");
  const last = { day: DAY, trigger: "routine_late", outcome: "would_claim", reason: null };
  assert.equal(X.movesLastText(last, "3 min ago"), `${DAY} · late routine: would claim, 3 min ago`);
  assert.equal(X.movesLastText(null, ""), "no pass from this browser yet");
  assert.deepEqual(X.dueLinks(due()), [{ id: e.id, href: `${SITE}${e.page}#pickandroll-moves-panel`, text: "add 3001, drop 2005, $3" }]);
});

test("the moves code clicks, toggles, sets, submits and fetches nothing", () => {
  for (const f of ["lib/moves.js", "league.js"]) {
    const src = fs.readFileSync(path.join(DIR, f), "utf8");
    assert.ok(!/\.click\(|dispatchEvent|submit\(|requestSubmit/.test(src), `${f} clicks or submits`);
    assert.ok(!/\.(value|selectedIndex|checked)\s*=[^=]/.test(src), `${f} sets a field`);
    assert.ok(!/\bfetch\(|XMLHttpRequest|DOMParser/.test(src), `${f} fetches a page`);
  }
});

// ---------------------------------------------------------------- the content script on an add page
/** A fake element: its text, attributes and children by selector. */
const el = (props = {}) => ({ textContent: "", className: "", getAttribute: (a) => (props.attrs || {})[a] ?? null, querySelectorAll: () => [], querySelector: () => null, closest: () => null, ...props });

/** The rendered add page as the content script sees it: the form, the noscript's submit as text,
 * the add's row and my roster's rows with their player ids and icons. */
function addDom({ add = ADD, budget = 100, waiver = "Oct 26" } = {}) {
  const input = (name, type, value) => ({ name, tagName: "INPUT", type, value, checked: false });
  const crumb = input("crumb", "hidden", "SECRET-TOKEN");
  const elements = [
    input("stage", "hidden", "2"),
    crumb,
    input("stat1", "hidden", "P"),
    input("stat2", "hidden", "P"),
    input("apid", "hidden", String(add)),
    ...ROSTER.filter((k) => !CANTCUT.includes(k)).map((k) => input("dpid", "checkbox", String(k))),
    input("faab", "text", "0"),
  ];
  const hint = el({ textContent: ` Must be between $0 and $${budget} ` });
  const form = el({ attrs: { action: `${SITE}/nba/${LEAGUE}/${TEAM}/addplayer`, method: "post" }, elements, querySelectorAll: (sel) => (sel === "p, span, div" ? [hint] : []) });
  const tr = (id, classes) =>
    el({
      querySelector: (sel) => (sel === "[data-ys-playerid]" ? el({ attrs: { "data-ys-playerid": String(id) } }) : null),
      querySelectorAll: (sel) => (sel === '[class*="T-action-icon-"]' && classes ? [el({ className: classes })] : []),
    });
  const addTr = tr(add, "noactionda- F-icon T-action-icon-disabled-add");
  const addCell = el({ attrs: { "data-ys-playerid": String(add) }, closest: (sel) => (sel === "tr" ? addTr : null) });
  const rows = ROSTER.map((k) => tr(k, CANTCUT.includes(k) ? ICON.cantcut : ""));
  return {
    crumb,
    querySelector: (sel) => (sel === "form#add-drop-players-form" ? form : sel === "table#statTable-add tbody tr [data-ys-playerid]" ? addCell : null),
    querySelectorAll: (sel) =>
      sel === "h1, h2, h3"
        ? [el({ textContent: "Yahoo Sports Fantasy Basketball" }), el({ textContent: ` ${X.CLAIM_HEADING} ` })]
        : sel === "table.statTable-drop tbody tr"
          ? rows
          : [],
    getElementById: (id) =>
      id === "faab-bid-fieldset"
        ? el({ textContent: `Your Bid $ Your Budget $${budget} Waiver Date ${waiver}` })
        : id === "add-drop-submit-container"
          ? el({ textContent: ` <input type="submit" id="submit-add-drop-button" name="${X.SUBMIT}" value="Create claim"> ` })
          : null,
  };
}

/** league.js on the add page of ``add`` (``hash`` its fragment), a chrome whose worker answers
 * each op with ``answer``. Returns the messages sent, the URLs replaced and the strip. */
async function visitAdd({ hash = "#pickandroll-moves", answer, add = ADD }) {
  const dom = addDom({ add });
  const nodes = {};
  const doc = {
    ...dom,
    getElementById: (id) => nodes[id] || dom.getElementById(id),
    createElement: () => ({ style: {}, setAttribute() {}, textContent: "" }),
    documentElement: {
      append: (e) => {
        nodes[e.id] = e;
      },
    },
  };
  const url = new URL(`${SITE}/nba/${LEAGUE}/addplayer?apid=${add}${hash}`);
  const location = { href: url.href, hash: url.hash, pathname: url.pathname, search: url.search, assign() {} };
  const sent = [];
  const replaced = [];
  const timers = [];
  const chrome = {
    runtime: {
      connect: () => ({}),
      getManifest: () => ({ version: "0.7.0" }),
      onMessage: { addListener() {} },
      sendMessage: async (msg) => {
        sent.push(JSON.parse(JSON.stringify(msg)));
        return answer(msg, sent);
      },
    },
  };
  const ctx = vm.createContext({
    chrome,
    location,
    document: doc,
    history: { replaceState: (_s, _t, u) => replaced.push(u) },
    setTimeout: (fn) => timers.push(fn),
    URL,
    URLSearchParams,
    Date,
    console,
  });
  ctx.window = ctx;
  ctx.globalThis = ctx;
  for (const file of ["lib/league.js", "lib/lineup.js", "lib/moves.js", "league.js"]) vm.runInContext(fs.readFileSync(path.join(DIR, file), "utf8"), ctx);
  for (const fn of timers.splice(0)) await fn();
  return { sent, replaced, strip: nodes["pickandroll-strip"] };
}

/** The worker's answers: the settings, the due entries and the log taking the pass. */
const worker =
  (over = {}, settings = {}) =>
  (msg) => {
    if (msg.op === "settings") return { ok: true, data: { lineup_executor: "on", moves_executor: "on", ...settings } };
    if (msg.op === "moves_due") return { ok: true, data: due(over) };
    if (msg.op === "moves_log") return { ok: true, data: { at: "x" } };
    return { ok: false, error: `unexpected ${msg.op}` };
  };
const ops = (v) => v.sent.map((m) => m.op);

test("the routine's link: the fragment dropped, the page's entry checked on the rendered form and the claim it would place logged", async () => {
  const v = await visitAdd({ answer: worker({ entries: [entry({ id: "other", add: 3002, page: `/nba/${LEAGUE}/addplayer?apid=3002` }), entry()] }) });
  assert.deepEqual(v.replaced, [`/nba/${LEAGUE}/addplayer?apid=${ADD}`]);
  // Nothing is posted for the add page: the due entries, then the pass.
  assert.deepEqual(ops(v), ["settings", "moves_due", "moves_log"]);
  assert.equal(v.sent[1].league, LEAGUE);
  const run = v.sent[2].run;
  assert.deepEqual([run.mode, run.trigger, run.outcome, run.extension], ["dry_run", "routine", "would_claim", "0.7.0"]);
  assert.deepEqual(run.entries.map((e) => [e.id, e.outcome]), [[entry().id, "would_claim"]]);
  const c = run.entries[0].controls;
  assert.deepEqual(c.would_fill, { action: `/nba/${LEAGUE}/${TEAM}/addplayer`, apid: ADD, dpid: 2005, faab: 3, submit: X.SUBMIT });
  assert.deepEqual([c.crumb, c.cantcut, c.add_markers, c.fields], ["present", CANTCUT, ["disabled_add"], ["stage", "stat1", "stat2"]]);
  assert.ok(!JSON.stringify(v.sent).includes("SECRET-TOKEN"), "the crumb's value never leaves the page");
  assert.match(v.strip.textContent, /^pickandroll moves: dry run · would claim for \$3, dropping 2005; logged \d\d:\d\d$/);
});

test("the late pass and the panel's link carry their triggers", async () => {
  let v = await visitAdd({ hash: "#pickandroll-moves-late", answer: worker() });
  assert.equal(v.sent[2].run.trigger, "routine_late");
  v = await visitAdd({ hash: "#pickandroll-moves-panel", answer: worker() });
  assert.equal(v.sent[2].run.trigger, "panel");
});

test("a plain visit runs nothing; a player not due logs nothing", async () => {
  let v = await visitAdd({ hash: "", answer: worker() });
  assert.deepEqual([ops(v), v.replaced], [[], []]);
  v = await visitAdd({ answer: worker({ entries: [] }) });
  assert.deepEqual(ops(v), ["settings", "moves_due"]);
  assert.equal(v.strip.textContent, "pickandroll moves: dry run · this player is not due in the queue: nothing logged");
});

test("off in the league, the browser's brake and STOP", async () => {
  let v = await visitAdd({ answer: worker({ mode: "off", entries: [] }) });
  assert.ok(!ops(v).includes("moves_log"));
  assert.equal(v.strip.textContent, "pickandroll moves: off in this league");
  v = await visitAdd({ answer: worker({}, { moves_executor: "off" }) });
  assert.deepEqual(ops(v), ["settings"]);
  assert.equal(v.strip.textContent, "pickandroll moves: off in this browser (the extension's settings)");
  v = await visitAdd({ answer: worker({ stop: true, entries: [] }) });
  assert.deepEqual([v.sent[2].run.outcome, v.sent[2].run.entries], ["stopped", []]);
});

test("a check that fails before the page still logs what the page showed", async () => {
  const v = await visitAdd({ answer: worker({ protected: { 2005: "kept: returns" } }) });
  const e = v.sent[2].run.entries[0];
  assert.deepEqual([e.outcome, e.reason], ["skipped", "the drop is protected (kept: returns)"]);
  assert.equal(e.controls.would_fill, null);
  assert.equal(e.controls.heading, X.CLAIM_HEADING);
});
