// node --test extension/test/*.test.js
// A churn's held drop (#221 part 3, ext 0.10.0): the drop_first item matched to the drop page,
// the page's checks, the two clicks on a fake drop page built from step 0c's read (2026-10-30: the
// row's button, Yahoo's confirm drawn in place, its submit "Drop <name>"), the landed page's
// answer (errno 933 or the notice, else unconfirmed), the content script on a drop page opened
// with a drop fragment and on the page Yahoo lands on, and the worker's record of a drop. Nothing
// here reaches Yahoo. Fixtures carry Yahoo ids and Yahoo's own words only; the name is made up.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const D = require("../lib/drop.js");

const DIR = path.join(__dirname, "..");
const SITE = "https://basketball.fantasysports.yahoo.com";
const LEAGUE = "100001";
const TEAM = 7;
const DAY = "2026-10-30";
const HELD = 6219;
const OTHER = 62190;
const ADD = 6038;
const MOVED = 5767;
const ENTRY = `${DAY}:${LEAGUE}:${ADD}:${HELD}`;
const NAME = "Test Player";
const PAGE = `/nba/${LEAGUE}/${TEAM}/dropplayer`;
const DROPPED_ALERTS = `abc123|${JSON.stringify([{ errno: 933, status: 0, params: [` dropped ${NAME}`] }])}`;

/** The due route's drop_first item, and the due answer (GET /seasons/{league}/autopilot/moves/due). */
const item = (over = {}) => ({ entry: ENTRY, player: HELD, slot: "IL", add: ADD, page: `${SITE}${PAGE}`, ...over });
const LIVE = { mode: "live", live: { ok: true, reason: null } };
const due = (over = {}, items = [item()]) => ({
  league: LEAGUE,
  team: TEAM,
  date: DAY,
  mode: "dry_run",
  stop: false,
  reason: null,
  entries: [],
  il_first: [],
  drop_first: items,
  ...over,
});
/** The due answer once the drop landed: the entry due with no drop, behind its IL move. */
const after = (il = true) => ({
  ...due(LIVE, []),
  entries: [{ id: ENTRY, add: ADD, drop: null, basis: "churn", page: `/nba/${LEAGUE}/addplayer?apid=${ADD}` }],
  il_first: il ? [{ entry: ENTRY, player: MOVED, slot: "IL", date: DAY, page: `${SITE}/nba/${LEAGUE}/${TEAM}?date=${DAY}` }] : [],
});

test("the triggers, the drop page and the item for it", () => {
  assert.equal(D.dropTriggerOf("#pickandroll-drop"), "routine");
  assert.equal(D.dropTriggerOf("#pickandroll-drop-late"), "routine_late");
  assert.equal(D.dropTriggerOf("#pickandroll-drop-evening"), "routine_evening");
  assert.equal(D.dropTriggerOf("#pickandroll-drop-panel"), "panel");
  assert.equal(D.dropTriggerOf("#pickandroll-il"), null);
  assert.deepEqual(Object.keys(D.DROP_THEN).sort(), Object.values(D.DROP_TRIGGERS).sort());
  assert.deepEqual(D.dropPageOf(`${SITE}${PAGE}#pickandroll-drop`), { league: LEAGUE, team: TEAM });
  assert.equal(D.dropPageOf(`${SITE}/nba/${LEAGUE}/${TEAM}`), null);
  assert.equal(D.dropPageOf(`${SITE}/nba/${LEAGUE}/addplayer?apid=${ADD}`), null);
  // One page serves every churn of the league: each visit takes the next not done.
  const two = due({}, [item(), item({ entry: "e2", player: OTHER })]);
  assert.equal(D.dropItemFor(two, PAGE).entry, ENTRY);
  assert.equal(D.dropItemFor(two, `${PAGE}/`, (x) => x.entry === ENTRY).entry, "e2");
  assert.equal(D.dropItemFor(two, PAGE, () => true), null);
  assert.equal(D.dropItemFor(two, `/nba/${LEAGUE}/8/dropplayer`), null);
  // A live drop submitted or sticky that day rules it out; a skip only for the same pass.
  assert.equal(D.ranToday(null, DAY, "live", "routine"), false);
  assert.equal(D.ranToday({ day: DAY, mode: "live", logged: false }, DAY, "live", "routine_late"), true);
  for (const o of D.DROP_STICKS) assert.equal(D.ranToday({ day: DAY, mode: "live", logged: true, outcome: o, trigger: "routine" }, DAY, "live", "routine_late"), true);
  const skipped = { day: DAY, mode: "live", logged: true, outcome: "skipped", trigger: "routine" };
  assert.equal(D.ranToday(skipped, DAY, "live", "routine"), true);
  assert.equal(D.ranToday(skipped, DAY, "live", "routine_late"), false);
  const dry = { day: DAY, mode: "dry_run", logged: true, outcome: "would_drop", trigger: "routine" };
  assert.equal(D.ranToday(dry, DAY, "dry_run", "routine"), true);
  assert.equal(D.ranToday(dry, DAY, "live", "routine"), false);
  assert.equal(D.ranToday({ ...dry, day: "2026-10-29" }, DAY, "dry_run", "routine"), false);
});

test("the next page after the drop: its IL move, else its add page, with the trigger's fragment", () => {
  assert.equal(D.dropNext(after(), ENTRY, "routine_late", SITE), `${SITE}/nba/${LEAGUE}/${TEAM}?date=${DAY}#pickandroll-il-late`);
  assert.equal(D.dropNext(after(false), ENTRY, "panel", SITE), `${SITE}/nba/${LEAGUE}/addplayer?apid=${ADD}#pickandroll-moves-panel`);
  assert.equal(D.dropNext(due(LIVE), ENTRY, "routine", SITE), null);
  assert.deepEqual(D.dropLinks(due(), true), [{ id: ENTRY, href: `${SITE}${PAGE}#pickandroll-drop-panel`, text: `drop: ${HELD} from IL, then its add ${ADD}` }]);
  assert.equal(D.dropLinks(due())[0].text, `${HELD} from IL, then its add ${ADD}`);
});

test("the page's checks: the form at stage 1, his one shown button with his name, nothing ticked", () => {
  const raw = (over = {}) => ({ path: PAGE, form: true, stage: "1", rows: [{ player: String(HELD), name: true, visible: true }, { player: String(OTHER), name: true, visible: true }], ticked: 0, ...over });
  const c = D.readDropPage(raw(), item());
  assert.deepEqual(c, { path: PAGE, form: true, stage: "1", rows: 1, trigger: true, name: true, ticked: 0 });
  assert.equal(D.dropProblem(c), null);
  const problem = (over) => D.dropProblem(D.readDropPage(raw(over), item()));
  assert.equal(problem({ form: false }), "the drop form is not on this page");
  assert.equal(problem({ stage: "2" }), "the drop form is at stage 2, not its first");
  assert.equal(problem({ rows: [] }), "the player is not on this page");
  // The id matched exactly: a longer id holding his is not his row.
  assert.equal(problem({ rows: [{ player: String(OTHER), name: true, visible: true }] }), "the player is not on this page");
  assert.equal(problem({ rows: [{ player: String(HELD), name: true, visible: false }] }), "the player's drop button is not shown");
  assert.equal(problem({ rows: [{ player: String(HELD), name: false, visible: true }] }), "the player's name is not on his row");
  assert.equal(problem({ ticked: 1 }), "a drop box was ticked before the run");
});

/** A fake drop page from step 0c: my rows at stage 1, each with a hidden box, a visible button
 * whose ``data-check-box-value`` is its id and a trailing space, and its name link. The button of
 * ``HELD`` re-renders the form ``after`` looks later as ``confirm`` says: ``ok`` (stage 2, one
 * hidden dpid, "Drop <name>"), ``dpid`` (another id), ``name`` (another name), ``stage`` (stage 1
 * still), ``none`` (never), ``alert`` (Yahoo's alert, no re-render). */
function dropDom({ confirm = "ok", after = 2, ticked = false, held = HELD } = {}) {
  const touched = [];
  const attrs = {};
  const field = (name, type, value, extra = {}) => ({ name, type, value: String(value), checked: false, ...extra });
  const shown = () => [{}];
  const link = (id, name) => ({ getAttribute: (a) => (a === "data-ys-playerid" ? String(id) : null), textContent: ` ${name} ` });
  const rowOf = (id, name) => ({ querySelectorAll: (sel) => (sel === D.DROP_NAME ? [link(id, name)] : []) });
  const button = (id, name, onClick) => ({
    getAttribute: (a) => (a === D.DROP_VALUE_ATTR ? `${id} ` : null),
    getClientRects: shown,
    closest: (sel) => (sel === "tr" ? rowOf(id, name) : null),
    click: () => onClick(),
  });
  let looks = null;
  let elements = [field("stage", "hidden", 1), field("stat1", "hidden", "S"), field("dpid", "checkbox", held, { checked: ticked }), field("dpid", "checkbox", OTHER)];
  let buttons;
  let submits = [];
  let text = "Drop Player Cancel";
  const submit = (value) => ({
    getAttribute: (a) => (a === "name" ? D.DROP_SUBMIT_NAME : null),
    value,
    getClientRects: shown,
    click: () => touched.push("click submit"),
  });
  const render = () => {
    buttons = [];
    if (confirm === "stage") return;
    const dpid = confirm === "dpid" ? OTHER : held;
    elements = [field("stage", "hidden", 2), field("stat1", "hidden", "S"), field("dpid", "hidden", dpid)];
    submits = [submit(`Drop ${confirm === "name" ? "Someone Else" : NAME}`)];
    text = `Drop ${NAME} Cancel`;
  };
  buttons = [
    button(held, NAME, () => {
      touched.push("click button");
      if (confirm === "alert") attrs["data-pickandroll-alerts"] = JSON.stringify(["You cannot drop this player."]);
      else if (confirm !== "none") looks = 0;
    }),
    button(OTHER, "Other Player", () => touched.push("click other")),
  ];
  const form = {
    get elements() {
      return elements;
    },
    get textContent() {
      return text;
    },
    querySelectorAll: (sel) => (sel === D.DROP_ROW_BUTTON ? buttons : sel === D.DROP_SUBMIT ? submits : []),
  };
  return {
    touched,
    look() {
      if (looks === null) return;
      looks += 1;
      if (looks === after) render();
    },
    querySelector: (sel) => (sel === D.DROP_FORM ? form : null),
    querySelectorAll: () => [],
    documentElement: { getAttribute: (a) => attrs[a] ?? null, setAttribute: (a, v) => (attrs[a] = v) },
    raw() {
      return {
        path: PAGE,
        form: true,
        stage: elements.filter((e) => e.name === "stage").map((e) => e.value).join(", "),
        rows: buttons.map((b) => ({ player: b.getAttribute(D.DROP_VALUE_ATTR).trim(), name: true, visible: true })),
        ticked: elements.filter((e) => e.name === "dpid" && e.checked).length,
      };
    },
  };
}
const drop = (dom, opts = {}, it = item()) => D.dropPlayer(dom, it, { wait: async () => dom.look(), every: 200, ...opts });

test("the drop: his row's button, then the confirm read as planned, then its one submit", async () => {
  const dom = dropDom();
  const confirms = [];
  const got = await drop(dom, { onConfirm: async (c) => confirms.push(c) > 0 });
  assert.equal(got, null);
  assert.deepEqual(dom.touched, ["click button", "click submit"]);
  assert.deepEqual(confirms, [{ stage: "2", dpid: `hidden=${HELD}`, submit: `Drop ${NAME}`, shown: true, name: true }]);
});

test("anything but the planned confirm stops before the submit, with the page's words", async () => {
  for (const confirm of ["dpid", "name", "stage", "none"]) {
    const dom = dropDom({ confirm });
    const got = await drop(dom, { cap: 1000 });
    assert.equal(got.outcome, "failed", confirm);
    assert.match(got.reason, /^stopped before the submit: the confirm did not show stage 2, dpid 6219 and "Drop Test Player" within 1 s$/);
    assert.ok(got.message, confirm);
    assert.deepEqual(dom.touched, ["click button"], confirm);
  }
  const dom = dropDom({ confirm: "alert" });
  const got = await drop(dom);
  assert.deepEqual([got.outcome, got.reason, dom.touched], ["failed", 'stopped before the submit: Yahoo answered the row\'s button: "You cannot drop this player."', ["click button"]]);
  assert.match(got.message, /^You cannot drop this player\./);
  // Not put on record: no submit.
  const held = dropDom();
  const no = await drop(held, { onConfirm: async () => false });
  assert.deepEqual([no.outcome, no.reason, held.touched], ["skipped", "the drop could not be put on record", ["click button"]]);
});

test("the drop clicks nothing when the page is not as planned", async () => {
  let dom = dropDom({ ticked: true });
  assert.deepEqual([(await drop(dom)).reason, dom.touched], ["a drop box was ticked before the run", []]);
  // A row whose id only begins with his is never his.
  dom = dropDom();
  assert.deepEqual([(await drop(dom, {}, item({ player: 621 }))).reason, dom.touched], ["no single shown drop button for 621 (0 on the page)", []]);
  dom = dropDom();
  assert.deepEqual([(await drop(dom, {}, item({ player: 1 }))).reason, dom.touched], ["no single shown drop button for 1 (0 on the page)", []]);
  const gone = { querySelector: () => null, documentElement: { getAttribute: () => null } };
  assert.equal((await D.dropPlayer(gone, item())).reason, "the drop form is gone");
});

test("only dropPlayer clicks among the drop code: two clicks, no field set, nothing fetched", () => {
  const dropped = D.dropPlayer.toString();
  const src = fs.readFileSync(path.join(DIR, "lib/drop.js"), "utf8").replace(dropped, "");
  assert.ok(!/\.click\(|dispatchEvent|submit\(|requestSubmit/.test(src), "lib/drop.js clicks outside dropPlayer");
  assert.ok(!/\.(value|selectedIndex|checked)\s*=[^=]/.test(src));
  assert.equal(dropped.match(/\.click\(\)/g).length, 2, "the row's button and the confirm's submit");
  assert.ok(!/\.(value|checked|selectedIndex)\s*=[^=]|dispatchEvent|submit\(|fetch\(|XMLHttpRequest|crumb|select/.test(dropped));
  assert.ok(!/\bfetch\(|XMLHttpRequest|DOMParser/.test(fs.readFileSync(path.join(DIR, "lib/drop.js"), "utf8")));
});

test("the landed page: errno 933 or the notice is dropped; anything else unconfirmed, never dropped", () => {
  let got = D.readDropLanded({ path: `/nba/${LEAGUE}/${TEAM}`, alerts: DROPPED_ALERTS, notices: [], shown: false });
  assert.deepEqual(got, { outcome: "dropped", message: `dropped ${NAME}`, landed: { path: `/nba/${LEAGUE}/${TEAM}`, errnos: [933], notice: null, shown: false } });
  got = D.readDropLanded({ alerts: null, notices: [` You have successfully dropped ${NAME} `] });
  assert.deepEqual([got.outcome, got.message], ["dropped", `You have successfully dropped ${NAME}`]);
  got = D.readDropLanded({ alerts: null, notices: [] });
  assert.deepEqual([got.outcome, got.message], ["unconfirmed", null]);
  got = D.readDropLanded({ alerts: `x|${JSON.stringify([{ errno: 12, status: 1, params: ["Something went wrong"] }])}`, notices: [] });
  assert.deepEqual([got.outcome, got.message, got.landed.errnos], ["unconfirmed", "Something went wrong", [12]]);
  assert.deepEqual(D.alertCodes("no bar"), []);
  assert.deepEqual(D.alertCodes("x|not json"), []);
  const record = { day: DAY, entry: ENTRY, player: HELD, trigger: "routine", page: PAGE, controls: { stage: "1" } };
  const run = D.landedDrop(record, D.readDropLanded({ alerts: DROPPED_ALERTS }), "0.10.0");
  assert.deepEqual([run.mode, run.outcome, run.reason, run.entry, run.player, run.extension], ["live", "dropped", null, ENTRY, HELD, "0.10.0"]);
  const unsure = D.landedDrop(record, D.readDropLanded({ alerts: null }));
  assert.deepEqual([unsure.outcome, unsure.reason], ["unconfirmed", "the landed page did not say he was dropped (no errno 933, no notice)"]);
  assert.deepEqual([D.landedDrop(record, null).outcome, D.landedDrop(record, null).reason], ["unconfirmed", "submitted; Yahoo's answer was not read"]);
});

test("the strip's lines", () => {
  const run = D.dropRun({ item: item(), day: DAY, trigger: "routine", mode: "live", outcome: "dropped", message: `You have successfully dropped ${NAME}` });
  assert.equal(D.dropStripText({ run, next: "x" }), `live · dropped ${HELD} · You have successfully dropped ${NAME} · going on`);
  assert.equal(D.dropStripText({ run: { ...run, mode: "dry_run", outcome: "would_drop", message: null } }), `dry run · would drop ${HELD}`);
  assert.equal(D.dropStripText({ browserOff: true }), "off in this browser (options page)");
});

test("the alert recorder: also on the drop page opened with a drop fragment", () => {
  const R = require("../addpage.js");
  assert.deepEqual([...R.DROP_FRAGMENTS].sort(), Object.keys(D.DROP_TRIGGERS).sort());
  const installed = (pathname, hash) => {
    const attrs = {};
    return R.install({ location: { pathname, hash }, alert() {}, document: { documentElement: { getAttribute: (a) => attrs[a] ?? null, setAttribute: (a, v) => (attrs[a] = v) } } });
  };
  for (const hash of Object.keys(D.DROP_TRIGGERS)) assert.equal(installed(PAGE, `#${hash}`), true);
  assert.equal(installed(PAGE, ""), false);
  assert.equal(installed(`/nba/${LEAGUE}/${TEAM}`, "#pickandroll-drop"), false);
});

// ---------------------------------------------------------------- the content script
/** league.js at ``url`` over ``dom`` (a drop page, or a landed page with its notices), a chrome
 * whose worker answers each op with ``answer``. Returns the messages sent, the URLs replaced and
 * assigned, the strip and the clicks. */
async function visit({ url = `${SITE}${PAGE}#pickandroll-drop`, answer, dom = dropDom(), notices = [], ids = [] }) {
  const nodes = {};
  const doc = {
    ...dom,
    querySelectorAll: (sel) => (sel === ".Alert, [role=alert]" ? notices.map((t) => ({ textContent: t })) : []),
    querySelector: (sel) => (sel.startsWith("[data-ys-playerid=") ? (ids.some((id) => sel === `[data-ys-playerid="${id}"]`) ? {} : null) : dom.querySelector(sel)),
    body: { textContent: "" },
    getElementById: (id) => nodes[id] || null,
    createElement: () => ({ style: {}, setAttribute() {}, textContent: "" }),
    documentElement: {
      ...dom.documentElement,
      append: (e) => {
        nodes[e.id] = e;
      },
      cloneNode: () => ({ querySelectorAll: () => [], outerHTML: "<html></html>" }),
    },
  };
  const u = new URL(url);
  const assigned = [];
  const location = { href: u.href, hash: u.hash, pathname: u.pathname, search: u.search, origin: u.origin, assign: (x) => assigned.push(x) };
  const sent = [];
  const replaced = [];
  const timers = [];
  const chrome = {
    runtime: {
      connect: () => ({}),
      getManifest: () => ({ version: "0.10.0" }),
      onMessage: { addListener() {} },
      sendMessage: async (msg) => {
        sent.push({ ...JSON.parse(JSON.stringify(msg)), clicks: dom.touched.length });
        return answer(msg, sent);
      },
    },
  };
  const ctx = vm.createContext({
    chrome,
    location,
    document: doc,
    history: { replaceState: (_s, _t, x) => replaced.push(x) },
    setTimeout: (fn) => {
      if (!ctx.started) timers.push(fn);
      else {
        dom.look();
        fn();
      }
    },
    URL,
    URLSearchParams,
    Date,
    console,
  });
  ctx.window = ctx;
  ctx.globalThis = ctx;
  for (const file of ["lib/league.js", "lib/lineup.js", "lib/moves.js", "lib/startactive.js", "lib/ilmove.js", "lib/drop.js", "league.js"]) vm.runInContext(fs.readFileSync(path.join(DIR, file), "utf8"), ctx);
  ctx.started = true;
  for (const fn of timers.splice(0)) await fn();
  return { sent, replaced, assigned, strip: nodes["pickandroll-strip"], touched: dom.touched };
}

/** The worker's answers: the settings, the due route (``d``, then ``next`` once a drop logged),
 * the record on file, a drop put on record (``kept``), the landing record and the log. */
const worker =
  (d = due(), { settings = {}, record = null, kept = true, landing = null, next = after() } = {}) =>
  (msg, sent) => {
    if (msg.op === "settings") return { ok: true, data: { lineup_executor: "on", moves_executor: "on", ...settings } };
    if (msg.op === "moves_landed") return { ok: true, data: null };
    if (msg.op === "drop_landed") return { ok: true, data: landing };
    if (msg.op === "moves_due") return { ok: true, data: sent.some((m) => m.op === "drop_log") ? next : d };
    if (msg.op === "drop_record") return { ok: true, data: record };
    if (msg.op === "drop_dropping") return kept ? { ok: true, data: { kept: true } } : { ok: false, error: "this drop awaits its log" };
    if (msg.op === "drop_log") return { ok: true, data: { at: "x" } };
    if (msg.op === "season_page") return { ok: true, data: { post: { accepted: [] }, follow: null } };
    return { ok: false, error: `unexpected ${msg.op}` };
  };
const ops = (v) => v.sent.map((m) => m.op);
const logOf = (v) => v.sent.filter((m) => m.op === "drop_log");
const RUN = ["moves_landed", "drop_landed", "settings", "moves_due", "drop_record"];

test("a dry run on the drop page logs would_drop and clicks nothing", async () => {
  const v = await visit({ answer: worker() });
  assert.deepEqual(ops(v), [...RUN, "drop_log"]);
  assert.deepEqual(v.replaced, [PAGE]);
  const [{ run }] = logOf(v);
  assert.deepEqual([run.mode, run.trigger, run.outcome, run.entry, run.player, run.page, run.extension], ["dry_run", "routine", "would_drop", ENTRY, HELD, PAGE, "0.10.0"]);
  assert.deepEqual(run.controls, { path: PAGE, form: true, stage: "1", rows: 1, trigger: true, name: true, ticked: 0 });
  assert.deepEqual([v.touched, v.assigned], [[], []]);
  assert.equal(v.strip.textContent, `pickandroll held drop: dry run · would drop ${HELD}`);
  // A live league whose guard refuses is a dry run that says why.
  const refused = await visit({ answer: worker(due({ mode: "live", live: { ok: false, reason: "the bar is red" } })) });
  assert.deepEqual([logOf(refused)[0].run.mode, logOf(refused)[0].run.reason, refused.touched], ["dry_run", "live refused: the bar is red", []]);
});

test("a live drop is put on record before its submit, and its submit is the last thing the page does", async () => {
  const v = await visit({ answer: worker(due(LIVE)) });
  assert.deepEqual(ops(v), [...RUN, "drop_dropping"]);
  const put = v.sent.find((m) => m.op === "drop_dropping");
  assert.deepEqual([put.clicks, put.record.entry, put.record.player, put.record.trigger, put.record.page], [1, ENTRY, HELD, "routine", PAGE]);
  assert.deepEqual(put.record.controls.confirm, { stage: "2", dpid: `hidden=${HELD}`, submit: `Drop ${NAME}`, shown: true, name: true });
  assert.deepEqual(v.touched, ["click button", "click submit"]);
  assert.equal(logOf(v).length, 0);
  assert.equal(v.strip.textContent, `pickandroll held drop: live · drop of ${HELD} submitted: reading Yahoo's answer…`);
  // Not put on record: skipped, no submit.
  const no = await visit({ answer: worker(due(LIVE), { kept: false }) });
  assert.deepEqual([logOf(no)[0].run.outcome, logOf(no)[0].run.reason, no.touched], ["skipped", "the drop could not be put on record: this drop awaits its log", ["click button"]]);
  // A confirm not as planned: failed, its words logged, no submit.
  const off = await visit({ answer: worker(due(LIVE)), dom: dropDom({ confirm: "dpid" }) });
  const [{ run }] = logOf(off);
  assert.deepEqual([run.mode, run.outcome, off.touched, off.assigned], ["live", "failed", ["click button"], []]);
  assert.match(run.reason, /^stopped before the submit: the confirm did not show/);
  assert.equal(run.controls.confirm.dpid, `hidden=${OTHER}`);
});

test("a drop on record or done today, STOP, no item and the brake click nothing", async () => {
  // Dropped live today: not taken again.
  let v = await visit({ answer: worker(due(LIVE), { record: { day: DAY, mode: "live", logged: true, outcome: "dropped", trigger: "routine" } }) });
  assert.deepEqual([ops(v), v.touched], [RUN, []]);
  assert.equal(v.strip.textContent, "pickandroll held drop: no held drop due on this page");
  // A submit on record past its landing whose run never came: logged unconfirmed first, then not taken.
  const stale = { day: DAY, entry: ENTRY, player: HELD, mode: "live", trigger: "routine", page: PAGE, logged: false, at: Date.now() - D.DROP_LANDING_MS - 1 };
  let reads = 0;
  const answer = worker(due(LIVE));
  v = await visit({ answer: (msg, sent) => (msg.op === "drop_record" ? { ok: true, data: reads++ ? { ...stale, logged: true, outcome: "unconfirmed" } : stale } : answer(msg, sent)) });
  assert.deepEqual([logOf(v)[0].run.outcome, logOf(v)[0].run.reason, v.touched], ["unconfirmed", "submitted; Yahoo's answer was not read", []]);
  // STOP: the run says it stopped.
  v = await visit({ answer: worker(due({ ...LIVE, stop: true, reason: "STOP is on" })) });
  assert.deepEqual([logOf(v)[0].run.outcome, logOf(v)[0].run.entry, v.touched], ["stopped", null, []]);
  // Off in this browser, and off in the league.
  v = await visit({ answer: worker(due(LIVE), { settings: { moves_executor: "off" } }) });
  assert.deepEqual([ops(v), v.touched], [["moves_landed", "drop_landed", "settings"], []]);
  v = await visit({ answer: worker(due({ mode: "off" })) });
  assert.deepEqual([ops(v).includes("drop_log"), v.touched], [false, []]);
  // No fragment: a plain visit of the drop page does nothing.
  v = await visit({ url: `${SITE}${PAGE}`, answer: worker(due(LIVE)) });
  assert.deepEqual([ops(v), v.touched], [["moves_landed", "drop_landed"], []]);
});

test("the page Yahoo lands on logs the drop and goes on to its IL move or add page", async () => {
  const landing = { day: DAY, entry: ENTRY, player: HELD, trigger: "routine_late", page: PAGE, controls: { stage: "1" }, league: LEAGUE, at: Date.now() };
  const landedUrl = `${SITE}/nba/${LEAGUE}/${TEAM}?date=${DAY}&st_pids=${HELD}&_global_alerts=${encodeURIComponent(DROPPED_ALERTS)}`;
  let v = await visit({ url: landedUrl, answer: worker(due(LIVE), { landing }) });
  assert.deepEqual(ops(v), ["moves_landed", "drop_landed", "drop_log", "moves_due"]);
  let [{ run }] = logOf(v);
  assert.deepEqual([run.mode, run.trigger, run.outcome, run.message, run.landed.errnos], ["live", "routine_late", "dropped", `dropped ${NAME}`, [933]]);
  assert.deepEqual(v.assigned, [`${SITE}/nba/${LEAGUE}/${TEAM}?date=${DAY}#pickandroll-il-late`]);
  // No IL move behind it: the add page.
  v = await visit({ url: landedUrl, answer: worker(due(LIVE), { landing, next: after(false) }) });
  assert.deepEqual(v.assigned, [`${SITE}/nba/${LEAGUE}/addplayer?apid=${ADD}#pickandroll-moves-late`]);
  // The notice alone says it too.
  v = await visit({ url: `${SITE}/nba/${LEAGUE}/${TEAM}`, answer: worker(due(LIVE), { landing }), notices: [`You have successfully dropped ${NAME}`] });
  assert.equal(logOf(v)[0].run.outcome, "dropped");
  // Neither: unconfirmed, logged, and nothing follows.
  v = await visit({ url: `${SITE}/nba/${LEAGUE}/${TEAM}`, answer: worker(due(LIVE), { landing }), ids: [HELD] });
  [{ run }] = logOf(v);
  assert.deepEqual([run.outcome, run.landed.shown, v.assigned], ["unconfirmed", true, []]);
  assert.deepEqual(ops(v).slice(0, 3), ["moves_landed", "drop_landed", "drop_log"]);
});

// ---------------------------------------------------------------- the worker
function loadWorker() {
  const store = new Map();
  const listeners = [];
  const fetches = [];
  const chrome = {
    runtime: { onMessage: { addListener: (fn) => listeners.push(fn) }, onConnect: { addListener() {} }, onInstalled: { addListener() {} }, onStartup: { addListener() {} }, getManifest: () => ({ version: "0.10.0" }) },
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
    fetches.push({ url, body: init.body ? JSON.parse(init.body) : null });
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

test("the worker keeps one drop on record: never submitted twice, logged once, read on landing", async () => {
  const w = loadWorker();
  const record = { day: DAY, entry: ENTRY, player: HELD, trigger: "routine", page: PAGE };
  assert.deepEqual((await w.send({ op: "drop_dropping", league: LEAGUE, record })).data, { kept: true });
  assert.equal((await w.send({ op: "drop_dropping", league: LEAGUE, record })).error, "this drop awaits its log");
  // Its landing: this tab's, this league's, not another's.
  assert.equal((await w.send({ op: "drop_landed", league: LEAGUE })).data.entry, ENTRY);
  assert.equal((await w.send({ op: "drop_landed", league: LEAGUE }, 8)).data, null);
  assert.equal((await w.send({ op: "drop_landed", league: "100009" })).data, null);
  const run = D.dropRun({ item: item(), day: DAY, trigger: "routine", mode: "live", outcome: "dropped" });
  assert.equal((await w.send({ op: "drop_log", league: LEAGUE, run })).ok, true);
  assert.equal(w.fetches.at(-1).url, `http://localhost:8000/seasons/${LEAGUE}/autopilot/drop`);
  const kept = (await w.send({ op: "drop_record", entry: ENTRY })).data;
  assert.deepEqual([kept.logged, kept.outcome, kept.mode, kept.trigger], [true, "dropped", "live", "routine"]);
  assert.equal((await w.send({ op: "drop_landed", league: LEAGUE })).data, null);
  assert.equal((await w.send({ op: "drop_dropping", league: LEAGUE, record })).error, "this drop is dropped today");
  // A live skip earlier that day does not stop a later submit; a refusal of a submitted drop ends it.
  const w2 = loadWorker();
  await w2.send({ op: "drop_log", league: LEAGUE, run: { ...run, outcome: "skipped" } });
  assert.deepEqual((await w2.send({ op: "drop_dropping", league: LEAGUE, record })).data, { kept: true });
  w2.refuse();
  assert.equal((await w2.send({ op: "drop_log", league: LEAGUE, run })).ok, false);
  const ended = (await w2.send({ op: "drop_record", entry: ENTRY })).data;
  assert.deepEqual([ended.logged, ended.refused], [true, "refused"]);
});
