// node --test extension/test/*.test.js
// A pending claim's cancel (#345 PR 2, ext 0.11.11): the claim's own View Details link taken from
// the Pending Transactions box (never another's), the claim's page checked against step 0's read
// (fixtures/cancel-page.html: form#edit-waiver-form posting to /editwaiver, the add's
// playernote link, one submit "s" = "Cancel Waiver"), the one press, Yahoo's confirm answered by
// addpage.js (yes only under the press's one-shot flag and only for words naming the cancel), my
// team page's box deciding the answer, the content script on each page, the worker's record and the
// step-0 reader's tidying. Nothing here reaches Yahoo; the names are made up.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const C = require("../lib/cancel.js");
const R = require("../addpage.js");
const CR = require("../lib/claimread.js");
const F = require("./fixtures/dom.js");

const DIR = path.join(__dirname, "..");
const SITE = "https://basketball.fantasysports.yahoo.com";
const LEAGUE = "100001";
const TEAM = 7;
const DAY = "2026-11-10";
const TEAM_PAGE = `/nba/${LEAGUE}/${TEAM}`;
const CLAIM = "7_6038_6733";
const CLAIM_URL = `${SITE}/nba/${LEAGUE}/${TEAM}/viewwaiver?claim_id=${CLAIM}`;
const FRAGMENT = "pickandroll-claim-cancel";
const PAGE_HTML = fs.readFileSync(path.join(__dirname, "fixtures/cancel-page.html"), "utf8");
const BOX_HTML = fs.readFileSync(path.join(__dirname, "fixtures/pending-box.html"), "utf8");

/** The cancels due: the claim page's (6038 for 6733) and an open spot in the box (6411). */
const ITEM = { entry: `2026-11-09:${LEAGUE}:6038:6733`, add: 6038, drop: 6733, bid: 2, reason: "below the floor", claim: CLAIM };
const OPEN = { entry: `2026-11-09:${LEAGUE}:6411:-`, add: 6411, drop: null, bid: 1, reason: "below the floor", claim: "7_6411_0" };
const LIVE = { mode: "live", live: { ok: true, reason: null } };
const due = (over = {}, cancels = [ITEM, OPEN]) => ({ league: LEAGUE, date: DAY, mode: "dry_run", stop: false, reason: null, team: TEAM, fragment: FRAGMENT, cancels, live: { ok: false, reason: "dry run first" }, ...over });

// ---------------------------------------------------------------- the pure parts
test("the claim's link is its own: team, add and drop exact, an open spot's drop 0, never another's", () => {
  const lines = [
    { href: `/nba/${LEAGUE}/7/viewwaiver?claim_id=7_10279_0&pspid=0`, text: "Waiver 1" },
    { href: `/nba/${LEAGUE}/7/viewwaiver?claim_id=7_6411_0&pspid=0`, text: "Waiver 2" },
    { href: `/nba/${LEAGUE}/7/viewwaiver?claim_id=7_6038_67330`, text: "Waiver 3" },
  ];
  assert.equal(C.cancelLink(lines, TEAM, OPEN), lines[1].href);
  // No fallback to the first link (step 0's read took the first; a cancel never does).
  assert.equal(C.cancelLink(lines, TEAM, ITEM), null);
  assert.equal(C.cancelLink(lines, 8, OPEN), null);
  assert.equal(C.cancelLink(null, TEAM, OPEN), null);
  assert.equal(C.claimIdOf(TEAM, { add: 6411, drop: null }), "7_6411_0");
  assert.equal(C.claimIdOf(null, ITEM), null);
  assert.equal(C.cancelTriggerOf(`#${FRAGMENT}`), "routine_evening");
  assert.equal(C.cancelTriggerOf("#pickandroll-claim-read"), null);
  assert.deepEqual(C.cancelPageOf(CLAIM_URL), { league: LEAGUE, team: TEAM, claim: CLAIM });
  assert.equal(C.cancelPageOf(`${SITE}/nba/${LEAGUE}/viewwaiver?claim_id=${CLAIM}`), null);
});

test("a claim runs once a pass: a live press unlogged or holding rules it out for good", () => {
  assert.equal(C.cancelRanToday(null, DAY, "live"), false);
  assert.equal(C.cancelRanToday({ mode: "live", logged: false, day: "2026-11-01" }, DAY, "live"), true);
  for (const outcome of C.CANCEL_STICKS) assert.equal(C.cancelRanToday({ mode: "live", logged: true, outcome, day: "2026-11-01" }, DAY, "live"), true);
  assert.equal(C.cancelRanToday({ mode: "live", logged: true, outcome: "skipped", day: DAY }, DAY, "live"), true);
  assert.equal(C.cancelRanToday({ mode: "live", logged: true, outcome: "skipped", day: "2026-11-09" }, DAY, "live"), false);
  assert.equal(C.cancelRanToday({ mode: "dry_run", logged: true, outcome: "would_cancel", day: DAY }, DAY, "live"), false);
  assert.deepEqual(C.cancelItemFor(due(), (x) => x.entry === ITEM.entry), OPEN);
});

/** The claim page's raw read as league.js's ``cancelControls`` gives it. */
const rawPage = (over = {}) => ({
  url: CLAIM_URL,
  forms: [
    { id: "search", action: "/search", players: [], buttons: [{ name: null, type: "submit", label: "Search" }] },
    {
      id: "edit-waiver-form",
      action: `/nba/${LEAGUE}/${TEAM}/editwaiver`,
      players: ["6038", "6038"],
      buttons: [
        { name: "s", type: "submit", label: "Save Bid" },
        { name: "s", type: "submit", label: "Cancel Waiver" },
      ],
      ...over,
    },
  ],
});

test("the claim's page is checked as step 0 read it before any press", () => {
  const want = { league: LEAGUE, team: TEAM, item: ITEM };
  const ok = C.readCancelPage(rawPage());
  assert.deepEqual(ok, { path: `/nba/${LEAGUE}/${TEAM}/viewwaiver`, claim: CLAIM, team: TEAM, league: LEAGUE, forms: 1, action: `/nba/${LEAGUE}/${TEAM}/editwaiver`, players: ["6038", "6038"], buttons: ["Save Bid", "Cancel Waiver"], cancel: 1 });
  assert.equal(C.cancelProblem(ok, want), null);
  const problem = (raw, w = want) => C.cancelProblem(C.readCancelPage(raw), w);
  assert.match(problem({ ...rawPage(), url: `${SITE}/nba/${LEAGUE}/${TEAM}/viewwaiver?claim_id=7_6038_1` }), /not 7_6038_6733/);
  assert.match(problem(rawPage(), { ...want, team: 8 }), /not 8_6038_6733/);
  assert.match(problem(rawPage({ action: `/nba/${LEAGUE}/8/editwaiver` })), /not my team's editwaiver/);
  assert.match(problem(rawPage({ action: `/nba/${LEAGUE}/${TEAM}/viewwaiver` })), /not my team's editwaiver/);
  assert.match(problem(rawPage({ players: ["10279"] })), /add 6038 is not named/);
  assert.match(problem(rawPage({ buttons: [{ name: "s", type: "submit", label: "Save Bid" }] })), /no Cancel Waiver button/);
  assert.match(problem(rawPage({ buttons: [{ name: "x", type: "submit", label: "Cancel Waiver" }] })), /no Cancel Waiver button/);
  assert.match(problem(rawPage({ buttons: [{ name: "s", type: "submit", label: "Cancel Waiver" }, { name: "s", type: "submit", label: " Cancel  Waiver " }] })), /more than one/);
  assert.match(problem({ url: CLAIM_URL, forms: [] }), /form is not on this page/);
});

// ---------------------------------------------------------------- Yahoo's confirm (addpage.js)
/** addpage.js installed on a fake window at ``pathname`` + ``hash``: its root's attributes. */
function installed(pathname = `/nba/${LEAGUE}/${TEAM}/viewwaiver`, hash = `#${FRAGMENT}`) {
  const attrs = {};
  const win = {
    location: { pathname, hash },
    alert() {},
    confirm: () => "unchanged",
    document: { documentElement: { getAttribute: (a) => attrs[a] ?? null, setAttribute: (a, v) => (attrs[a] = String(v)), removeAttribute: (a) => delete attrs[a] } },
  };
  return { on: R.install(win), win, attrs, confirms: () => JSON.parse(attrs[R.CONFIRMS_ATTR] || "[]") };
}

test("the confirm says yes only under the press's one-shot flag, and only to words naming the cancel", () => {
  const p = installed();
  assert.equal(p.on, true);
  // The flag down: no.
  assert.equal(p.win.confirm("Are you sure you want to cancel this waiver claim?"), false);
  // The flag up, other words: no, and the flag is taken down.
  p.attrs[R.ARMED_ATTR] = "1";
  assert.equal(p.win.confirm("Leave this page?"), false);
  assert.equal(p.attrs[R.ARMED_ATTR], undefined);
  // The flag up, the cancel's words: yes, once.
  p.attrs[R.ARMED_ATTR] = "1";
  assert.equal(p.win.confirm("Are you sure you want to cancel this waiver claim?"), true);
  assert.equal(p.win.confirm("Are you sure you want to cancel this waiver claim?"), false);
  // Every confirm's words are kept, with the answer.
  assert.deepEqual(
    p.confirms().map((c) => [c.yes, c.armed]),
    [
      [false, false],
      [false, true],
      [true, true],
      [false, false],
    ]
  );
  assert.equal(p.confirms()[1].text, "Leave this page?");
  for (const yes of ["Cancel waiver?", "Do you want to cancel your claim", "CANCEL this Waiver Claim"]) assert.equal(R.namesCancel(yes), true);
  for (const no of ["Save bid?", "Cancel?", "Drop this waiver player?", ""]) assert.equal(R.namesCancel(no), false);
  // Its own copy matches the library's.
  for (const t of ["Cancel waiver?", "Cancel?", "claim cancelled", "Leave?"]) assert.equal(R.namesCancel(t), C.confirmNamesCancel(t));
});

test("the confirm is left alone off the claim's page opened with the cancel's fragment", () => {
  for (const [p, h] of [
    [`/nba/${LEAGUE}/${TEAM}/viewwaiver`, ""],
    [`/nba/${LEAGUE}/${TEAM}/viewwaiver`, "#pickandroll-claim-read"],
    [TEAM_PAGE, `#${FRAGMENT}`],
    [`/nba/${LEAGUE}/${TEAM}/editwaiver`, `#${FRAGMENT}`],
  ]) {
    const x = installed(p, h);
    assert.equal(x.win.confirm("Cancel waiver?"), "unchanged", `${p}${h}`);
  }
  // The add page's alert keeper still leaves confirm alone.
  const add = installed(`/nba/${LEAGUE}/addplayer`, "#pickandroll-moves");
  assert.equal(add.on, true);
  assert.equal(add.win.confirm("Cancel waiver?"), "unchanged");
  assert.deepEqual(R.CANCEL_FRAGMENTS, Object.keys(C.CANCEL_TRIGGERS));
});

// ---------------------------------------------------------------- the press
/** A fake claim page from the fixture whose "Cancel Waiver" click asks ``confirm`` (null: none)
 * through addpage.js, and whose Save Bid is never to be touched. */
function pageDom({ html = PAGE_HTML, confirm = "Are you sure you want to cancel this waiver claim?", alert = null, hash = `#${FRAGMENT}` } = {}) {
  const root = F.parse(html);
  const attrs = {};
  const touched = [];
  const posted = [];
  const documentElement = { getAttribute: (a) => attrs[a] ?? null, setAttribute: (a, v) => (attrs[a] = String(v)), removeAttribute: (a) => delete attrs[a] };
  const win = { location: { pathname: `/nba/${LEAGUE}/${TEAM}/viewwaiver`, hash }, alert() {}, document: { documentElement } };
  R.install(win);
  for (const b of root.querySelectorAll("input, button")) {
    b.click = () => {
      touched.push(b.getAttribute("value") || b.textContent);
      if (alert) win.alert(alert);
      if (confirm === null || win.confirm(confirm)) posted.push(`${b.getAttribute("name")}=${b.getAttribute("value")}`);
    };
  }
  return { querySelectorAll: (s) => root.querySelectorAll(s), querySelector: (s) => root.querySelector(s), documentElement, attrs, touched, posted, root };
}

test("the press clicks Cancel Waiver once, with its confirm said yes, the flag taken down", async () => {
  const dom = pageDom();
  let recorded = 0;
  const got = await C.pressCancel(dom, ITEM, { onPress: async () => ++recorded > 0 });
  assert.deepEqual(got, { pressed: true, confirm: "Are you sure you want to cancel this waiver claim?" });
  assert.deepEqual([recorded, dom.touched, dom.posted], [1, ["Cancel Waiver"], ["s=Cancel Waiver"]]);
  assert.equal(dom.attrs[C.CONFIRM_ARMED_ATTR], undefined);
  // No confirm at all: the press goes.
  const none = pageDom({ confirm: null });
  assert.deepEqual(await C.pressCancel(none, ITEM), { pressed: true, confirm: null });
  assert.deepEqual(none.posted, ["s=Cancel Waiver"]);
});

test("a confirm in other words is answered no and the run is not_cancelled with its words", async () => {
  const dom = pageDom({ confirm: "You have unsaved changes. Leave?" });
  const got = await C.pressCancel(dom, ITEM);
  assert.equal(got.outcome, "not_cancelled");
  assert.match(got.reason, /did not name the cancel and was answered no: "You have unsaved changes. Leave\?"/);
  assert.deepEqual([dom.touched, dom.posted], [["Cancel Waiver"], []]);
  // Yahoo's alert after the press: failed, with its words.
  const alerted = pageDom({ confirm: null, alert: "Error 845: transactions are locked" });
  const a = await C.pressCancel(alerted, ITEM);
  assert.deepEqual([a.outcome, a.reason], ["failed", 'Yahoo answered the press: "Error 845: transactions are locked"']);
});

test("nothing is pressed when the record does not take or the page is not as read", async () => {
  let dom = pageDom();
  assert.deepEqual(await C.pressCancel(dom, ITEM, { onPress: async () => false }), { outcome: "skipped", reason: "the press could not be put on record", confirm: null });
  assert.deepEqual(dom.touched, []);
  dom = pageDom({ html: PAGE_HTML.replace('value="Cancel Waiver"/>', 'value="Cancel Waiver"/><input type="submit" name="s" value="Cancel Waiver"/>') });
  assert.match((await C.pressCancel(dom, ITEM)).reason, /2 Cancel Waiver buttons/);
  dom = pageDom();
  assert.match((await C.pressCancel(dom, { ...ITEM, add: 10279 })).reason, /add 10279 is not named/);
  dom = pageDom({ html: PAGE_HTML.replace('id="edit-waiver-form"', 'id="other-form"') });
  assert.equal((await C.pressCancel(dom, ITEM)).reason, "the claim's form is gone");
  assert.deepEqual(dom.touched, []);
});

test("my team page's box decides: the claim gone is cancelled, still there is not, a form again is not", () => {
  const box = [{ href: `/nba/${LEAGUE}/7/viewwaiver?claim_id=7_10279_0` }];
  assert.deepEqual(C.settleCancel(box, CLAIM, true), { outcome: "cancelled", reason: null });
  assert.deepEqual(C.settleCancel([...box, { href: `/nba/${LEAGUE}/7/viewwaiver?claim_id=${CLAIM}&pspid=0` }], CLAIM, true), { outcome: "not_cancelled", reason: "the claim is still among Yahoo's pending transactions" });
  // No box: cancelled only on a page that shows my roster.
  assert.deepEqual(C.settleCancel(null, CLAIM, true), { outcome: "cancelled", reason: null });
  assert.equal(C.settleCancel(null, CLAIM, false), null);
  assert.equal(C.readCancelLanded({ path: TEAM_PAGE, form: false }), null);
  const again = C.readCancelLanded({ path: `/nba/${LEAGUE}/${TEAM}/editwaiver`, form: true, heading: "Confirm", notes: ["Are you sure?"] });
  assert.deepEqual([again.outcome, again.message], ["not_cancelled", "Confirm · Are you sure?"]);
});

test("lib/cancel.js clicks once, in pressCancel, and never submits a form, sets a field or fetches", () => {
  const src = fs.readFileSync(path.join(DIR, "lib/cancel.js"), "utf8");
  assert.equal((src.match(/\.click\(/g) || []).length, 1);
  assert.ok(!/dispatchEvent|\.submit\(|requestSubmit|\bfetch\(|XMLHttpRequest|\.value\s*=[^=]|faab/.test(src));
});

// ---------------------------------------------------------------- the content script
/** league.js (with addpage.js) at ``url`` over ``html``; the worker answers each op with
 * ``answer``. Returns the messages sent, the URLs assigned and replaced, the strip and the
 * page's clicks. */
async function visit({ url, html, answer, confirm }) {
  const dom = pageDom({ html, confirm, hash: new URL(url).hash });
  const nodes = {};
  const doc = {
    querySelectorAll: (sel) => dom.root.querySelectorAll(sel),
    querySelector: (sel) => dom.root.querySelector(sel),
    getElementById: (id) => nodes[id] || null,
    createElement: () => ({ setAttribute() {}, style: {}, textContent: "" }),
    body: dom.root,
    documentElement: {
      ...dom.documentElement,
      append: (el) => (nodes[el.id] = el),
      cloneNode: () => ({ querySelectorAll: () => [], outerHTML: "<html></html>" }),
    },
  };
  const u = new URL(url);
  const assigned = [];
  const replaced = [];
  const sent = [];
  const later = [];
  const location = { href: u.href, hash: u.hash, pathname: u.pathname, search: u.search, origin: u.origin, assign: (x) => assigned.push(x), reload() {} };
  const chrome = {
    runtime: {
      connect: () => ({}),
      getManifest: () => ({ version: "0.11.11" }),
      onMessage: { addListener() {} },
      sendMessage: async (msg) => {
        sent.push({ ...JSON.parse(JSON.stringify(msg)), clicks: dom.touched.length });
        return answer(msg, sent);
      },
    },
  };
  let started = false;
  const timers = [];
  const ctx = vm.createContext({
    chrome,
    location,
    document: doc,
    history: { replaceState: (_s, _t, x) => replaced.push(x) },
    setTimeout: (fn, ms) => (started ? later.push({ fn, ms }) : timers.push(fn)),
    URL,
    URLSearchParams,
    Date,
    console,
  });
  ctx.window = ctx;
  ctx.globalThis = ctx;
  for (const file of ["lib/league.js", "lib/lineup.js", "lib/moves.js", "lib/startactive.js", "lib/ilmove.js", "lib/drop.js", "lib/claimread.js", "lib/cancel.js", "league.js"]) vm.runInContext(fs.readFileSync(path.join(DIR, file), "utf8"), ctx);
  started = true;
  for (const fn of timers.splice(0)) await fn();
  return { sent, assigned, replaced, later, strip: nodes["pickandroll-strip"], touched: dom.touched, posted: dom.posted, ops: sent.map((m) => m.op) };
}

/** The worker's answers: the settings, the cancels due, the record, the landing and the log. */
const worker =
  (d = due(), { settings = {}, record = null, kept = true, landing = null } = {}) =>
  (msg) => {
    if (msg.op === "settings") return { ok: true, data: { lineup_executor: "on", moves_executor: "on", ...settings } };
    if (msg.op === "moves_landed" || msg.op === "drop_landed") return { ok: true, data: null };
    if (msg.op === "cancel_landed") return { ok: true, data: landing };
    if (msg.op === "cancel_due") return { ok: true, data: d };
    if (msg.op === "cancel_record") return { ok: true, data: record };
    if (msg.op === "cancel_pressing") return kept ? { ok: true, data: { kept: true } } : { ok: false, error: "this cancel awaits its log" };
    if (msg.op === "cancel_settling" || msg.op === "cancel_log") return { ok: true, data: { at: "x" } };
    if (msg.op === "season_page") return { ok: true, data: { post: { accepted: [] }, follow: null } };
    return { ok: false, error: `unexpected ${msg.op}` };
  };
const logOf = (v) => v.sent.filter((m) => m.op === "cancel_log").map((m) => m.run);

test("my team page with the fragment follows the due claim's own link, clicking nothing", async () => {
  // ITEM is not in the box: logged skipped and the next visit takes the next claim.
  let v = await visit({ url: `${SITE}${TEAM_PAGE}?date=${DAY}#${FRAGMENT}`, html: BOX_HTML, answer: worker() });
  let [run] = logOf(v);
  assert.deepEqual([run.outcome, run.mode, run.entry, run.claim, v.assigned, v.touched], ["skipped", "dry_run", ITEM.entry, CLAIM, [], []]);
  assert.equal(run.reason, "the claim is not among Yahoo's pending transactions on my team page");
  // The open spot is in the box: its own link, with the fragment.
  v = await visit({ url: `${SITE}${TEAM_PAGE}?date=${DAY}#${FRAGMENT}`, html: BOX_HTML, answer: worker(due({}, [OPEN])) });
  assert.deepEqual(v.assigned, [`${SITE}/nba/${LEAGUE}/7/viewwaiver?claim_id=7_6411_0&pspid=0&activity=transaction#${FRAGMENT}`]);
  assert.deepEqual([logOf(v), v.touched, v.replaced], [[], [], [`${TEAM_PAGE}?date=${DAY}`]]);
  // A claim that ran today in this mode is not taken again.
  v = await visit({ url: `${SITE}${TEAM_PAGE}#${FRAGMENT}`, html: BOX_HTML, answer: worker(due({}, [OPEN]), { record: { mode: "dry_run", day: DAY, logged: true, outcome: "would_cancel" } }) });
  assert.deepEqual([v.assigned, logOf(v)], [[], []]);
  assert.match(v.strip.textContent, /nothing to cancel/);
});

test("the brake, the executor off, the private league and STOP take nothing further", async () => {
  const url = `${SITE}${TEAM_PAGE}#${FRAGMENT}`;
  let v = await visit({ url, html: BOX_HTML, answer: worker(due({}, [OPEN]), { settings: { moves_executor: "off" } }) });
  assert.deepEqual([v.assigned, logOf(v), v.ops.includes("cancel_due")], [[], [], false]);
  v = await visit({ url, html: BOX_HTML, answer: worker(due({ mode: "off", cancels: [], reason: "the moves executor is off in this league" })) });
  assert.deepEqual([v.assigned, logOf(v)], [[], []]);
  v = await visit({ url, html: BOX_HTML, answer: worker(due({ mode: "dry_run", cancels: [], reason: "the private league is never touched" })) });
  assert.deepEqual([v.assigned, logOf(v)], [[], []]);
  v = await visit({ url, html: BOX_HTML, answer: worker(due({ stop: true, reason: "STOP is on (data/autopilot/STOP)", cancels: [] })) });
  const [run] = logOf(v);
  assert.deepEqual([run.outcome, run.entry, v.assigned], ["stopped", null, []]);
  // On the claim's page too.
  v = await visit({ url: `${CLAIM_URL}#${FRAGMENT}`, html: PAGE_HTML, answer: worker(due(LIVE), { settings: { moves_executor: "off" } }) });
  assert.deepEqual([v.touched, logOf(v)], [[], []]);
});

test("a dry run on the claim's page checks it and logs would_cancel, clicking nothing", async () => {
  let v = await visit({ url: `${CLAIM_URL}#${FRAGMENT}`, html: PAGE_HTML, answer: worker() });
  let [run] = logOf(v);
  assert.deepEqual([run.mode, run.outcome, run.reason, run.entry, run.claim, run.add, run.drop, run.page], ["dry_run", "would_cancel", null, ITEM.entry, CLAIM, 6038, 6733, `/nba/${LEAGUE}/${TEAM}/viewwaiver`]);
  assert.deepEqual([run.controls.action, run.controls.cancel, run.controls.buttons], [`/nba/${LEAGUE}/${TEAM}/editwaiver`, 1, ["Save Bid", "Cancel Waiver"]]);
  assert.deepEqual([v.touched, v.posted, v.replaced], [[], [], [`/nba/${LEAGUE}/${TEAM}/viewwaiver?claim_id=${CLAIM}`]]);
  assert.ok(!JSON.stringify(run).includes("crumb"));
  // A live league whose guard refuses: a dry run with the reason.
  v = await visit({ url: `${CLAIM_URL}#${FRAGMENT}`, html: PAGE_HTML, answer: worker(due({ mode: "live", live: { ok: false, reason: "STOP" } })) });
  [run] = logOf(v);
  assert.deepEqual([run.mode, run.outcome, run.reason, v.touched], ["dry_run", "would_cancel", "live refused: STOP", []]);
  // The page not as read: skipped, nothing clicked, in a live league too.
  v = await visit({ url: `${CLAIM_URL}#${FRAGMENT}`, html: PAGE_HTML.replace("/nba/100001/7/editwaiver", "/nba/100001/7/dropplayer"), answer: worker(due(LIVE)) });
  [run] = logOf(v);
  assert.deepEqual([run.mode, run.outcome, v.touched], ["live", "skipped", []]);
  assert.match(run.reason, /not my team's editwaiver/);
  // A claim page the due does not name: nothing at all.
  v = await visit({ url: `${CLAIM_URL}#${FRAGMENT}`, html: PAGE_HTML, answer: worker(due(LIVE, [OPEN])) });
  assert.deepEqual([logOf(v), v.touched], [[], []]);
  // Without the fragment the page is a plain visit.
  v = await visit({ url: CLAIM_URL, html: PAGE_HTML, answer: worker(due(LIVE)) });
  assert.deepEqual([v.ops.includes("cancel_due"), v.touched], [false, []]);
});

test("a live league puts the press on record, then presses Cancel Waiver once and waits for Yahoo", async () => {
  let v = await visit({ url: `${CLAIM_URL}#${FRAGMENT}`, html: PAGE_HTML, answer: worker(due(LIVE)) });
  const put = v.sent.find((m) => m.op === "cancel_pressing");
  assert.deepEqual([put.clicks, put.record.claim, put.record.item.entry, put.record.team, put.record.trigger], [0, CLAIM, ITEM.entry, TEAM_PAGE, "routine_evening"]);
  assert.deepEqual([v.touched, v.posted, logOf(v)], [["Cancel Waiver"], ["s=Cancel Waiver"], []]);
  assert.equal(v.strip.textContent, `pickandroll cancel: live · cancel of claim ${CLAIM} pressed: reading Yahoo's answer…`);
  // A page that stays goes to my team page to read the box.
  assert.equal(v.later.length, 1);
  assert.equal(v.later[0].ms, C.CANCEL_STAY_MS);
  // The record refused: nothing pressed, a live skip logged.
  v = await visit({ url: `${CLAIM_URL}#${FRAGMENT}`, html: PAGE_HTML, answer: worker(due(LIVE), { kept: false }) });
  const [run] = logOf(v);
  assert.deepEqual([run.mode, run.outcome, v.touched], ["live", "skipped", []]);
  assert.equal(run.reason, "the press could not be put on record: this cancel awaits its log");
  // A confirm in other words: answered no, logged not_cancelled with its words.
  v = await visit({ url: `${CLAIM_URL}#${FRAGMENT}`, html: PAGE_HTML, answer: worker(due(LIVE)), confirm: "Save your bid first?" });
  const [no] = logOf(v);
  assert.deepEqual([no.outcome, no.controls.confirm, v.posted], ["not_cancelled", "Save your bid first?", []]);
  // A press on record from this pass is never pressed again.
  v = await visit({ url: `${CLAIM_URL}#${FRAGMENT}`, html: PAGE_HTML, answer: worker(due(LIVE), { record: { mode: "live", logged: true, outcome: "not_cancelled", day: DAY } }) });
  assert.deepEqual([v.touched, logOf(v)], [[], []]);
});

/** The press on record for this tab, as the worker keeps it. */
const landing = (over = {}) => ({ day: DAY, item: ITEM, claim: CLAIM, trigger: "routine_evening", page: `/nba/${LEAGUE}/${TEAM}/viewwaiver`, controls: { cancel: 1 }, team: TEAM_PAGE, mode: "live", logged: false, at: Date.now(), ...over });

test("after the press, my team page's box decides and every other page goes there first", async () => {
  // Yahoo lands somewhere else: the read kept, on to my team page.
  let v = await visit({ url: `${SITE}/nba/${LEAGUE}/${TEAM}/editwaiver`, html: '<div><h1>Done</h1><div class="Alert">Your waiver claim was cancelled</div></div>', answer: worker(due(LIVE), { landing: landing() }) });
  const settle = v.sent.find((m) => m.op === "cancel_settling");
  assert.deepEqual([settle.entry, settle.settle.seen.heading, settle.settle.seen.notes, v.assigned, logOf(v)], [ITEM.entry, "Done", ["Your waiver claim was cancelled"], [`${SITE}${TEAM_PAGE}`], []]);
  // On my team page, the box without the claim: cancelled.
  const settled = landing({ settle: { seen: { path: "/x", heading: "Done" } } });
  v = await visit({ url: `${SITE}${TEAM_PAGE}`, html: BOX_HTML, answer: worker(due(LIVE), { landing: settled }) });
  let [run] = logOf(v);
  assert.deepEqual([run.mode, run.outcome, run.entry, run.landed.heading, v.assigned], ["live", "cancelled", ITEM.entry, "Done", []]);
  assert.equal(v.strip.textContent, `pickandroll cancel: live · claim ${CLAIM} cancelled on Yahoo`);
  // The box still lists it: not cancelled.
  const listed = BOX_HTML.replace("claim_id=7_10279_0", `claim_id=${CLAIM}`);
  v = await visit({ url: `${SITE}${TEAM_PAGE}`, html: listed, answer: worker(due(LIVE), { landing: settled }) });
  [run] = logOf(v);
  assert.deepEqual([run.outcome, run.reason], ["not_cancelled", "the claim is still among Yahoo's pending transactions"]);
  // No box, my roster shown: cancelled; neither: unconfirmed.
  v = await visit({ url: `${SITE}${TEAM_PAGE}`, html: '<div><a data-ys-playerid="6038">x</a></div>', answer: worker(due(LIVE), { landing: settled }) });
  assert.equal(logOf(v)[0].outcome, "cancelled");
  v = await visit({ url: `${SITE}${TEAM_PAGE}`, html: "<div><p>Oops</p></div>", answer: worker(due(LIVE), { landing: settled }) });
  assert.equal(logOf(v)[0].outcome, "unconfirmed");
  // Yahoo draws a form again on the claim's pages: not cancelled, nothing more clicked.
  v = await visit({ url: CLAIM_URL, html: PAGE_HTML, answer: worker(due(LIVE), { landing: landing() }) });
  [run] = logOf(v);
  assert.deepEqual([run.outcome, v.touched, v.assigned], ["not_cancelled", [], []]);
  assert.match(run.reason, /form again/);
  // The heading's parts are read with spaces between them (step 0 ran them together).
  assert.equal(run.landed.heading, "Test Player Player Note SAC - PF,C");
  // A number-only notice is left out.
  assert.deepEqual(run.landed.notes, []);
});

test("a landing logged on my team page opened for the next cancel goes on to that cancel", async () => {
  const settled = landing({ settle: { seen: { path: "/x", heading: "Done" } } });
  const v = await visit({ url: `${SITE}${TEAM_PAGE}#${FRAGMENT}`, html: BOX_HTML, answer: worker(due(LIVE, [OPEN]), { landing: settled }) });
  assert.deepEqual(logOf(v).map((r) => [r.entry, r.outcome]), [[ITEM.entry, "cancelled"]]);
  assert.deepEqual(v.assigned, [`${SITE}/nba/${LEAGUE}/7/viewwaiver?claim_id=7_6411_0&pspid=0&activity=transaction#${FRAGMENT}`]);
});

test("a press whose answer never came is logged unconfirmed on the next visit, never pressed again", async () => {
  const stale = landing({ at: Date.now() - C.CANCEL_LANDING_MS - 1000 });
  const v = await visit({ url: `${CLAIM_URL}#${FRAGMENT}`, html: PAGE_HTML, answer: worker(due(LIVE), { record: stale }) });
  const [run] = logOf(v);
  assert.deepEqual([run.mode, run.outcome, run.entry], ["live", "unconfirmed", ITEM.entry]);
  assert.deepEqual(v.touched, []);
});

// ---------------------------------------------------------------- the worker
function loadWorker() {
  const store = new Map();
  const listeners = [];
  const fetches = [];
  const chrome = {
    runtime: { onMessage: { addListener: (fn) => listeners.push(fn) }, onConnect: { addListener() {} }, onInstalled: { addListener() {} }, onStartup: { addListener() {} }, getManifest: () => ({ version: "0.11.11" }) },
    sidePanel: { setPanelBehavior: async () => {} },
    storage: {
      local: {
        get: async (k) => (k === null ? Object.fromEntries(store) : Object.fromEntries((Array.isArray(k) ? k : [k]).filter((x) => store.has(x)).map((x) => [x, store.get(x)]))),
        set: async (o) => Object.entries(o).forEach(([k, v]) => store.set(k, v)),
        remove: async (k) => (Array.isArray(k) ? k : [k]).forEach((x) => store.delete(x)),
      },
      session: { get: async () => ({}), set: async () => {}, remove: async () => {} },
    },
  };
  let status = 200;
  const fetch = async (url, init) => {
    fetches.push({ url, method: init.method, body: init.body ? JSON.parse(init.body) : null });
    return { ok: status < 400, status, text: async () => JSON.stringify(status < 400 ? { at: "x" } : { detail: "refused" }) };
  };
  const ctx = vm.createContext({ chrome, fetch, AbortController, setTimeout, clearTimeout, console, URL });
  ctx.self = ctx;
  ctx.importScripts = (...files) => {
    for (const f of files) vm.runInContext(fs.readFileSync(path.join(DIR, f), "utf8"), ctx);
  };
  vm.runInContext(fs.readFileSync(path.join(DIR, "worker.js"), "utf8"), ctx);
  const send = (msg, tab = 1) =>
    new Promise((resolve) => {
      const reply = (r) => resolve(JSON.parse(JSON.stringify(r)));
      for (const fn of listeners) if (fn(msg, { tab: { id: tab } }, reply) === true) return;
      resolve(undefined);
    });
  return { send, store, fetches, refuse: () => (status = 409) };
}

test("the worker keeps one press on record: never pressed twice, read on landing, logged once", async () => {
  const w = loadWorker();
  const record = { day: DAY, item: ITEM, claim: CLAIM, trigger: "routine_evening", page: "/p", team: TEAM_PAGE };
  assert.equal((await w.send({ op: "cancel_pressing", league: LEAGUE, record })).ok, true);
  const again = await w.send({ op: "cancel_pressing", league: LEAGUE, record });
  assert.deepEqual([again.ok, again.error], [false, "this cancel awaits its log"]);
  // The landing reads it in the same tab and league only.
  assert.equal((await w.send({ op: "cancel_landed", league: LEAGUE })).data.claim, CLAIM);
  assert.equal((await w.send({ op: "cancel_landed", league: LEAGUE }, 8)).data, null);
  assert.equal((await w.send({ op: "cancel_landed", league: "100009" })).data, null);
  assert.equal((await w.send({ op: "cancel_settling", league: LEAGUE, entry: ITEM.entry, settle: { seen: { heading: "Done" } } })).ok, true);
  assert.equal((await w.send({ op: "cancel_landed", league: LEAGUE })).data.settle.seen.heading, "Done");
  // Logged: posted to the league's cancel route, the record now the run.
  const run = C.cancelRun({ day: DAY, mode: "live", trigger: "routine_evening", outcome: "not_cancelled", item: ITEM, claim: CLAIM });
  assert.equal((await w.send({ op: "cancel_log", league: LEAGUE, run })).ok, true);
  assert.match(w.fetches.at(-1).url, new RegExp(`/seasons/${LEAGUE}/autopilot/cancel$`));
  assert.equal(w.fetches.at(-1).method, "POST");
  assert.equal((await w.send({ op: "cancel_landed", league: LEAGUE })).data, null);
  const kept = (await w.send({ op: "cancel_record", league: LEAGUE, entry: ITEM.entry })).data;
  assert.deepEqual([kept.logged, kept.outcome], [true, "not_cancelled"]);
  // Never pressed again.
  const held = await w.send({ op: "cancel_pressing", league: LEAGUE, record });
  assert.deepEqual([held.ok, held.error], [false, "this cancel is not_cancelled: it is never pressed again"]);
  // The due is the league's own route.
  await w.send({ op: "cancel_due", league: LEAGUE });
  assert.match(w.fetches.at(-1).url, new RegExp(`/seasons/${LEAGUE}/autopilot/cancels$`));
});

test("a refused log of a pressed cancel still ends its record: it is never pressed again", async () => {
  const w = loadWorker();
  const record = { day: DAY, item: ITEM, claim: CLAIM, trigger: "routine_evening", page: "/p", team: TEAM_PAGE };
  await w.send({ op: "cancel_pressing", league: LEAGUE, record });
  w.refuse();
  const run = C.cancelRun({ day: DAY, mode: "live", trigger: "routine_evening", outcome: "cancelled", item: ITEM, claim: CLAIM });
  assert.equal((await w.send({ op: "cancel_log", league: LEAGUE, run })).ok, false);
  const kept = (await w.send({ op: "cancel_record", league: LEAGUE, entry: ITEM.entry })).data;
  assert.deepEqual([kept.logged, kept.outcome, Boolean(kept.refused)], [true, "cancelled", true]);
});

// ---------------------------------------------------------------- step 0's reader, tidied
test("the claim page's read drops the stats tabs and the number-only notes, and keeps the claim's own", () => {
  const raw = {
    url: CLAIM_URL,
    heading: "Test Player Player Note SAC - PF,C",
    notes: ["337", "654", "Your claim is pending"],
    forms: [
      {
        id: "edit-waiver-form",
        controls: [
          { tag: "a", text: "Stats", href: `/nba/${LEAGUE}/${TEAM}/viewwaiver?claim_id=${CLAIM}&stat1=S` },
          { tag: "a", text: "Last 7 Days", href: `/nba/${LEAGUE}/${TEAM}/viewwaiver?stat2=L7` },
          { tag: "a", text: "Bid $2 for Test Player", href: `/nba/${LEAGUE}/${TEAM}/viewwaiver?claim_id=${CLAIM}` },
          { tag: "a", text: "Test Player", href: "https://sports.yahoo.com/nba/players/6038" },
          { tag: "input", type: "submit", name: "s", label: "Cancel Waiver" },
        ],
      },
    ],
  };
  const read = CR.claimPageRead(raw, { trigger: "routine_evening", readAt: 0 });
  assert.deepEqual(read.notes, ["Your claim is pending"]);
  assert.deepEqual(
    read.forms[0].controls.map((c) => c.text),
    ["Bid $2 for Test Player", "Test Player", "Cancel Waiver"]
  );
});
