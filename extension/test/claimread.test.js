// The read of a pending claim's page (#345 step 0): the pure helpers, and league.js on my team
// page (the box's link followed) and on the claim's page (names and words read, never a value,
// nothing clicked).
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const C = require("../lib/claimread.js");
const F = require("./fixtures/dom.js");

const DIR = path.join(__dirname, "..");
const SITE = "https://basketball.fantasysports.yahoo.com";
const LEAGUE = "100001";
const TEAM = 7;
const FRAGMENT = "pickandroll-claim-read";
const BOX = fs.readFileSync(path.join(__dirname, "fixtures", "pending-box.html"), "utf8");
const BOX_DROP = fs.readFileSync(path.join(__dirname, "fixtures", "pending-box-drop.html"), "utf8");
/** A made-up claim page (not Yahoo's markup, which is what the read is for): a crumb in a hidden
 * field and in the action's and links' queries, a typed bid, the header's search form. */
const CLAIM = fs.readFileSync(path.join(__dirname, "fixtures", "claim-page.html"), "utf8");
const CLAIM_URL = `${SITE}/nba/${LEAGUE}/${TEAM}/viewwaiver?claim_id=7_6038_6733&pspid=0&activity=transaction`;

test("the read's fragment, and the claim's page by its path and claim id", () => {
  assert.equal(C.claimReadTriggerOf(`#${FRAGMENT}`), "routine_evening");
  assert.equal(C.claimReadTriggerOf(FRAGMENT), "routine_evening");
  assert.equal(C.claimReadTriggerOf("#pickandroll-moves-evening"), null);
  assert.equal(C.claimReadTriggerOf(""), null);
  assert.deepEqual(C.claimPageOf(CLAIM_URL), { league: LEAGUE, team: TEAM, claim: "7_6038_6733" });
  assert.deepEqual(C.claimPageOf(`${SITE}/nba/${LEAGUE}/viewwaiver?claim_id=7_1_0`), { league: LEAGUE, team: null, claim: "7_1_0" });
  assert.deepEqual(C.claimPageOf(`${SITE}/nba/${LEAGUE}/${TEAM}/viewwaiver?claim_id=x`), { league: LEAGUE, team: TEAM, claim: null });
  assert.equal(C.claimPageOf(`${SITE}/nba/${LEAGUE}/${TEAM}`), null);
  assert.equal(C.claimPageOf(`${SITE}/nba/${LEAGUE}/${TEAM}/addplayer?apid=1`), null);
  assert.equal(C.claimPageOf(`https://example.com/nba/${LEAGUE}/${TEAM}/viewwaiver?claim_id=7_1_0`), null);
  assert.equal(C.claimPageOf("not a url"), null);
});

test("the link followed is the due claim's, by its add and drop, else the box's first", () => {
  const lines = (html) => F.parse(html).querySelectorAll('a[href*="viewwaiver"]').map((a) => ({ href: a.getAttribute("href"), text: a.textContent }));
  const box = lines(BOX);
  assert.match(C.claimLink(box, { add: 6411, drop: null }), /claim_id=7_6411_0&/);
  assert.match(C.claimLink(box, { add: 10279, drop: null }), /claim_id=7_10279_0&/);
  assert.match(C.claimLink(lines(BOX_DROP), { add: 6038, drop: 6733 }), /claim_id=7_6038_6733&/);
  // Not on the box: the first claim's link.
  assert.equal(C.claimLink(box, { add: 5471, drop: 1 }), box[0].href);
  assert.equal(C.claimLink(box, null), box[0].href);
  // No box, an empty box, links that name no claim.
  assert.equal(C.claimLink(null, { add: 1 }), null);
  assert.equal(C.claimLink([], { add: 1 }), null);
  assert.equal(C.claimLink([{ href: "/nba/1/7/viewwaiver", text: "x" }], { add: 1 }), null);
});

test("a path is kept without its query or fragment, a page of another host keeps its host", () => {
  assert.equal(C.plainPath("/nba/1/7/viewwaiver?claim_id=7_1_0&crumb=abc#x", CLAIM_URL), "/nba/1/7/viewwaiver");
  assert.equal(C.plainPath("cancelwaiver?crumb=abc", CLAIM_URL), `/nba/${LEAGUE}/${TEAM}/cancelwaiver`);
  assert.equal(C.plainPath("https://login.yahoo.com/account?done=1", CLAIM_URL), "//login.yahoo.com/account");
  assert.equal(C.plainPath("javascript:void(0)", CLAIM_URL), "javascript:");
  assert.equal(C.plainPath("mailto:a@b.c", CLAIM_URL), "mailto:");
  assert.equal(C.plainPath("", CLAIM_URL), null);
  assert.equal(C.plainPath(null, CLAIM_URL), null);
});

test("the read keeps names and words only: no field's value, query or crumb, whatever the raw page holds", () => {
  const raw = {
    url: `${CLAIM_URL}#${FRAGMENT}`,
    heading: "  Waiver \n Claim ",
    notes: ["Pending", "Pending", "", "x".repeat(500)],
    forms: [
      {
        id: "f",
        name: null,
        method: "POST",
        action: "/nba/100001/7/viewwaiver?crumb=SECRETCRUMB",
        fields: [{ tag: "INPUT", type: "hidden", name: "crumb", id: null, value: "SECRETCRUMB" }],
        controls: [
          { tag: "input", type: "submit", name: "cancel", id: null, text: null, label: "Cancel Claim", href: null },
          { tag: "input", type: "text", name: "faab", id: null, text: null, label: "3", href: null },
          { tag: "a", type: null, name: null, id: null, text: "Edit", label: null, href: "/x?crumb=SECRETCRUMB" },
        ],
      },
    ],
    controls: [{ tag: "button", type: "submit", name: null, id: null, text: "Back", label: null, href: null, value: "v" }],
  };
  const read = C.claimPageRead(raw, { trigger: "routine_evening", readAt: Date.UTC(2026, 10, 9, 4, 40), extension: "0.11.10" });
  assert.deepEqual(read, {
    trigger: "routine_evening",
    read_at: "2026-11-09T04:40:00.000Z",
    claim: "7_6038_6733",
    path: `/nba/${LEAGUE}/${TEAM}/viewwaiver`,
    heading: "Waiver Claim",
    notes: ["Pending", "x".repeat(200)],
    forms: [
      {
        id: "f",
        name: null,
        method: "post",
        action: "/nba/100001/7/viewwaiver",
        fields: [{ tag: "input", type: "hidden", name: "crumb", id: null }],
        controls: [
          { tag: "input", type: "submit", name: "cancel", id: null, text: "Cancel Claim", path: null },
          { tag: "input", type: "text", name: "faab", id: null, text: null, path: null },
          { tag: "a", type: null, name: null, id: null, text: "Edit", path: "/x" },
        ],
      },
    ],
    controls: [{ tag: "button", type: "submit", name: null, id: null, text: "Back", path: null }],
    extension: "0.11.10",
  });
  const text = JSON.stringify(read);
  assert.ok(!text.includes("SECRETCRUMB"));
  assert.ok(!/"value"/.test(text));
  // The API's caps: rows dropped past them.
  const many = C.claimPageRead({ url: CLAIM_URL, forms: Array(30).fill({ fields: Array(150).fill({ tag: "input" }), controls: [] }), controls: Array(80).fill({ tag: "button", text: "b" }) }, { trigger: "routine_evening", readAt: 0 });
  assert.deepEqual([many.forms.length, many.forms[0].fields.length, many.controls.length, many.heading, many.extension], [20, 100, 50, null, null]);
});

test("lib/claimread.js clicks, submits and fetches nothing", () => {
  const src = fs.readFileSync(path.join(DIR, "lib/claimread.js"), "utf8");
  assert.ok(!/\.click\(|dispatchEvent|submit\(|requestSubmit|\bfetch\(|XMLHttpRequest/.test(src));
});

/** league.js on ``url`` over the fixture ``html``: the worker's answers from ``answer``. */
async function visit({ url, html, answer }) {
  const root = F.parse(html);
  const nodes = {};
  const doc = {
    querySelectorAll: (sel) => root.querySelectorAll(sel),
    querySelector: (sel) => root.querySelector(sel),
    getElementById: (id) => nodes[id] || root.querySelector(`#${id}`),
    createElement: () => ({ setAttribute() {}, style: {}, textContent: "" }),
    documentElement: { append: (el) => (nodes[el.id] = el), cloneNode: () => ({ querySelectorAll: () => [], outerHTML: "<html></html>" }) },
    body: root,
  };
  const u = new URL(url);
  const assigned = [];
  const replaced = [];
  const sent = [];
  const timers = [];
  const location = { href: u.href, hash: u.hash, pathname: u.pathname, search: u.search, origin: u.origin, assign: (x) => assigned.push(x) };
  const chrome = {
    runtime: {
      connect: () => ({}),
      getManifest: () => ({ version: "0.11.10" }),
      onMessage: { addListener() {} },
      sendMessage: async (msg) => {
        sent.push(JSON.parse(JSON.stringify(msg)));
        return answer(msg);
      },
    },
  };
  const ctx = vm.createContext({
    chrome,
    location,
    document: doc,
    history: { replaceState: (_s, _t, x) => replaced.push(x) },
    setTimeout: (fn) => timers.push(fn),
    URL,
    URLSearchParams,
    Date,
    console,
  });
  ctx.window = ctx;
  ctx.globalThis = ctx;
  for (const file of ["lib/league.js", "lib/lineup.js", "lib/moves.js", "lib/startactive.js", "lib/ilmove.js", "lib/drop.js", "lib/claimread.js", "league.js"]) vm.runInContext(fs.readFileSync(path.join(DIR, file), "utf8"), ctx);
  for (const fn of timers.splice(0)) await fn();
  return { sent, assigned, replaced, strip: nodes["pickandroll-strip"], ops: sent.map((m) => m.op) };
}

const due = (over = {}) => ({ date: "2026-11-08", fragment: FRAGMENT, reads: 0, due: true, reason: null, league: LEAGUE, claim: "e1", add: 6038, drop: 6733, page: `${SITE}/nba/${LEAGUE}/${TEAM}?date=2026-11-08`, ...over });
const worker =
  (d = due(), { settings = {}, read = { ok: true, data: { league: LEAGUE } } } = {}) =>
  (msg) => {
    if (msg.op === "settings") return { ok: true, data: { lineup_executor: "on", moves_executor: "on", ...settings } };
    if (msg.op === "moves_landed" || msg.op === "drop_landed") return { ok: true, data: null };
    if (msg.op === "claim_page_due") return { ok: true, data: d };
    if (msg.op === "claim_page_read") return read;
    if (msg.op === "season_page") return { ok: true, data: { post: { accepted: [] }, follow: null } };
    return { ok: false, error: `unexpected ${msg.op}` };
  };
const BEFORE = ["moves_landed", "drop_landed", "settings", "claim_page_due"];

test("on my team page with the fragment the box's link of the due claim is followed with it, nothing clicked", async () => {
  const team = `${SITE}/nba/${LEAGUE}/${TEAM}#${FRAGMENT}`;
  let v = await visit({ url: team, html: BOX_DROP, answer: worker() });
  assert.deepEqual(v.ops, BEFORE);
  assert.deepEqual(v.replaced, [`/nba/${LEAGUE}/${TEAM}`]);
  assert.deepEqual(v.assigned, [`${SITE}/nba/${LEAGUE}/${TEAM}/viewwaiver?claim_id=7_6038_6733&pspid=0&activity=transaction#${FRAGMENT}`]);
  assert.equal(v.strip.textContent, "pickandroll claim read: reading the claim's page; nothing is clicked");
  // No box on the page: nowhere to go, the strip says so.
  v = await visit({ url: team, html: "<div><h1>Team</h1></div>", answer: worker() });
  assert.deepEqual([v.ops, v.assigned], [BEFORE, []]);
  assert.equal(v.strip.textContent, "pickandroll claim read: no claim page read: no View Details link in the Pending Transactions box");
  // Not due (a read on file), due in another league, the brake on: nothing followed.
  v = await visit({ url: team, html: BOX_DROP, answer: worker(due({ due: false, reason: "a read of the claim page is on file" })) });
  assert.deepEqual([v.assigned, v.strip.textContent], [[], "pickandroll claim read: no claim page read: a read of the claim page is on file"]);
  v = await visit({ url: team, html: BOX_DROP, answer: worker(due({ league: "100002" })) });
  assert.deepEqual([v.assigned, v.strip.textContent], [[], "pickandroll claim read: no claim page read: the read is due in league 100002"]);
  v = await visit({ url: team, html: BOX_DROP, answer: worker(due(), { settings: { moves_executor: "off" } }) });
  assert.deepEqual([v.ops, v.assigned], [["moves_landed", "drop_landed", "settings"], []]);
  // Without the fragment my team page is a plain visit: no read asked for.
  v = await visit({ url: `${SITE}/nba/${LEAGUE}/${TEAM}`, html: BOX_DROP, answer: worker() });
  assert.ok(!v.ops.includes("claim_page_due"));
  assert.deepEqual(v.assigned, []);
});

test("on the claim's page with the fragment the read is filed: forms, fields and buttons by name and words, never a value", async () => {
  const v = await visit({ url: `${CLAIM_URL}#${FRAGMENT}`, html: CLAIM, answer: worker() });
  assert.deepEqual(v.ops, [...BEFORE, "claim_page_read"]);
  assert.deepEqual([v.assigned, v.replaced], [[], [`/nba/${LEAGUE}/${TEAM}/viewwaiver?claim_id=7_6038_6733&pspid=0&activity=transaction`]]);
  const { league, read } = v.sent.find((m) => m.op === "claim_page_read");
  assert.equal(league, LEAGUE);
  assert.deepEqual([read.trigger, read.claim, read.path, read.heading, read.notes, read.extension], ["routine_evening", "7_6038_6733", `/nba/${LEAGUE}/${TEAM}/viewwaiver`, "Waiver Claim", ["Your claim is pending"], "0.11.10"]);
  // The header's search form is Yahoo's, not the claim's.
  assert.deepEqual(read.forms, [
    {
      id: "claim-form",
      name: "claim",
      method: "post",
      action: `/nba/${LEAGUE}/${TEAM}/viewwaiver`,
      fields: [
        { tag: "input", type: "hidden", name: "crumb", id: null },
        { tag: "input", type: "hidden", name: "claim_id", id: null },
        { tag: "input", type: "text", name: "faab", id: "bid" },
        { tag: "select", type: null, name: "priority", id: null },
      ],
      controls: [
        { tag: "input", type: "submit", name: "cancel", id: null, text: "Cancel Claim", path: null },
        { tag: "button", type: "submit", name: "edit", id: null, text: "Edit Claim", path: null },
        { tag: "a", type: null, name: null, id: null, text: "Edit bid", path: `/nba/${LEAGUE}/${TEAM}/editwaiver` },
      ],
    },
  ]);
  // Outside the forms: the buttons and the claim's links, not the league's other links.
  assert.deepEqual(read.controls, [
    { tag: "a", type: null, name: null, id: null, text: "Cancel", path: `/nba/${LEAGUE}/${TEAM}/cancelwaiver` },
    { tag: "a", type: null, name: null, id: null, text: "Contact", path: "mailto:" },
    { tag: "button", type: "submit", name: null, id: null, text: "Back", path: null },
  ]);
  const text = JSON.stringify(read);
  for (const secret of ["SECRETCRUMB", "typed words", "claims@example.com", '"value"', "claim_id=", '"3"']) assert.ok(!text.includes(secret), secret);
  assert.equal(v.strip.textContent, "pickandroll claim read: claim page read and filed: 1 form, 6 controls; nothing clicked");
});

test("the claim's page files nothing when the read is not due, without the fragment, or when the post fails", async () => {
  let v = await visit({ url: `${CLAIM_URL}#${FRAGMENT}`, html: CLAIM, answer: worker(due({ due: false, reason: "STOP is on (data/autopilot/STOP)" })) });
  assert.deepEqual(v.ops, BEFORE);
  assert.equal(v.strip.textContent, "pickandroll claim read: no claim page read: STOP is on (data/autopilot/STOP)");
  v = await visit({ url: CLAIM_URL, html: CLAIM, answer: worker() });
  assert.deepEqual(v.ops, ["moves_landed", "drop_landed"]);
  v = await visit({ url: `${CLAIM_URL}#${FRAGMENT}`, html: CLAIM, answer: worker(due(), { read: { ok: false, error: "422 a path is read without its query" } }) });
  assert.deepEqual(v.ops, [...BEFORE, "claim_page_read"]);
  assert.equal(v.strip.textContent, "pickandroll claim read: the claim page's read failed: 422 a path is read without its query");
});

test("league.js's claim read clicks, submits and fetches nothing", () => {
  const src = fs.readFileSync(path.join(DIR, "league.js"), "utf8");
  const start = src.indexOf("// ---------------------------------------------------------------- a claim page's read");
  const end = src.indexOf("// A live pass submits only on a page opened with a moves fragment");
  assert.ok(start > 0 && end > start);
  assert.ok(!/\.click\(|dispatchEvent|submit\(|requestSubmit|\bfetch\(|XMLHttpRequest|\.value\b/.test(src.slice(start, end)));
});
