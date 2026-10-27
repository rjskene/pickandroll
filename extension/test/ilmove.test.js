// node --test extension/test/*.test.js
// The IL move an open-spot claim needs first (#214, ext 0.9.1): the il_first item matched to the
// page, the swap controls' checks, the two clicks on a fake team page built from step 0's read
// (2026-10-27: the player's slot label, then the empty IL row's, which saves at once), the content
// script on a team page opened with an IL fragment and its way on to the claim's add page, the
// claim's wait for a move dated later, and the worker's record of a move. Nothing here reaches
// Yahoo. Fixtures carry Yahoo ids and Yahoo's own words only.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const I = require("../lib/ilmove.js");

const DIR = path.join(__dirname, "..");
const SITE = "https://basketball.fantasysports.yahoo.com";
const LEAGUE = "100001";
const TEAM = 7;
const DAY = "2026-10-27";
const HELD = 6219;
const ADD = 6038;
const ENTRY = `${DAY}:${LEAGUE}:${ADD}:0`;
const SAVED = "All changes saved";

/** The due route's il_first item, and the due answer (GET /seasons/{league}/autopilot/moves/due). */
const item = (over = {}) => ({ entry: ENTRY, player: HELD, slot: "IL", date: DAY, tip: null, page: `${SITE}/nba/${LEAGUE}/${TEAM}?date=${DAY}`, ...over });
const LIVE = { mode: "live", live: { ok: true, reason: null } };
const due = (over = {}, items = [item()]) => ({
  league: LEAGUE,
  team: TEAM,
  date: DAY,
  mode: "dry_run",
  stop: false,
  reason: null,
  entries: [{ id: ENTRY, add: ADD, drop: null, basis: "held", held_move: { player: HELD, slot: "IL" }, page: `/nba/${LEAGUE}/addplayer?apid=${ADD}` }],
  il_first: items,
  ...over,
});

test("the triggers, the item for the page and the add page after it", () => {
  assert.equal(I.ilTriggerOf("#pickandroll-il"), "routine");
  assert.equal(I.ilTriggerOf("#pickandroll-il-late"), "routine_late");
  assert.equal(I.ilTriggerOf("#pickandroll-il-evening"), "routine_evening");
  assert.equal(I.ilTriggerOf("#pickandroll-il-panel"), "panel");
  for (const h of ["", "#pickandroll-start-active", "#pickandroll-moves", "#pickandroll-lineup"]) assert.equal(I.ilTriggerOf(h), null);
  assert.deepEqual(Object.keys(I.IL_THEN).sort(), Object.values(I.IL_TRIGGERS).sort());
  // The item whose page is this page: my team, the item's date.
  assert.equal(I.ilItemFor(due(), `/nba/${LEAGUE}/${TEAM}?date=${DAY}`).entry, ENTRY);
  assert.equal(I.ilItemFor(due(), `/nba/${LEAGUE}/${TEAM}?date=2026-10-28`), null);
  assert.equal(I.ilItemFor(due(), `/nba/${LEAGUE}/${TEAM}`), null);
  assert.equal(I.ilItemFor(due(), `/nba/${LEAGUE}/3?date=${DAY}`), null);
  assert.equal(I.ilItemFor(due({}, []), `/nba/${LEAGUE}/${TEAM}?date=${DAY}`), null);
  // On to the entry's add page, the trigger's moves fragment; none when the entry is not due.
  assert.equal(I.ilNext(due(), item(), "routine", SITE), `${SITE}/nba/${LEAGUE}/addplayer?apid=${ADD}#pickandroll-moves`);
  assert.equal(I.ilNext(due(), item(), "routine_evening", SITE), `${SITE}/nba/${LEAGUE}/addplayer?apid=${ADD}#pickandroll-moves-evening`);
  assert.equal(I.ilNext(due(), item(), "panel", SITE), `${SITE}/nba/${LEAGUE}/addplayer?apid=${ADD}#pickandroll-moves-panel`);
  assert.equal(I.ilNext({ ...due(), entries: [] }, item(), "routine", SITE), null);
  // The panel's links: the team page with the panel's fragment.
  assert.deepEqual(I.ilLinks(due(), true), [{ id: ENTRY, href: `${SITE}/nba/${LEAGUE}/${TEAM}?date=${DAY}#pickandroll-il-panel`, text: `move: ${HELD} to IL (dated ${DAY}), then its claim` }]);
  assert.equal(I.ilLinks(due())[0].text, `${HELD} to IL (dated ${DAY}), then its claim`);
});

/** The swap controls as the content script reads them, from today's markup: rows with their
 * player, editable and empty classes and slot labels. */
const rawRows = ({ held = "C", heldEditable = true, heldButton = true, il = true, editable = true, dupe = false } = {}) => ({
  path: `/nba/${LEAGUE}/${TEAM}?date=${DAY}`,
  editable,
  rows: [
    { player: 5767, editable: true, empty: false, labels: [{ pos: "PG", button: true, visible: true }] },
    { player: HELD, editable: heldEditable, empty: false, labels: [{ pos: held, button: heldButton, visible: true }] },
    ...(dupe ? [{ player: HELD, editable: true, empty: false, labels: [{ pos: "BN", button: true, visible: true }] }] : []),
    { player: null, editable: true, empty: true, labels: [{ pos: "BN", button: true, visible: false }, { pos: "BN", button: true, visible: false }] },
    ...(il ? [{ player: null, editable: true, empty: true, labels: [{ pos: "IL", button: true, visible: false }, { pos: "IL", button: true, visible: false }] }] : []),
  ],
});

test("the page checks: editable, the player once with one visible button label, an empty slot of the item's", () => {
  const c = I.readILPage(rawRows(), item());
  assert.deepEqual(c, { path: `/nba/${LEAGUE}/${TEAM}?date=${DAY}`, editable: true, rows: 1, from_slot: "C", movable: true, targets: 1 });
  assert.equal(I.ilProblem(item(), c), null);
  const why = (over, it = item()) => I.ilProblem(it, I.readILPage(rawRows(over), it));
  assert.equal(why({ editable: false }), "the roster is not editable on this page");
  assert.equal(why({}, item({ player: 9999 })), "the player is not on this page");
  assert.equal(why({ dupe: true }), "the player shows more than once on this page");
  assert.equal(why({ held: "IL" }), "the player is on IL already");
  assert.equal(why({ heldEditable: false }), "the player's slot is locked on this page");
  assert.equal(why({ heldButton: false }), "the player's slot is locked on this page");
  assert.equal(why({ il: false }), "no empty IL slot on this page");
  assert.equal(why({}, item({ slot: "IL+" })), "no empty IL+ slot on this page");
});

test("the run the log takes, an unread move, the strip and the claim's wait", () => {
  const controls = I.readILPage(rawRows(), item());
  const run = I.ilRun({ item: item(), day: DAY, trigger: "routine", mode: "live", outcome: "moved", message: SAVED, controls, page: `/nba/${LEAGUE}/${TEAM}?date=${DAY}`, extension: "0.9.1" });
  assert.deepEqual(Object.keys(run).sort(), ["controls", "dated", "day", "entry", "extension", "from_slot", "message", "mode", "outcome", "page", "player", "reason", "to_slot", "trigger"]);
  assert.deepEqual([run.entry, run.player, run.from_slot, run.to_slot, run.dated], [ENTRY, HELD, "C", "IL", DAY]);
  assert.equal(I.ilStripText({ run, next: "x" }), `live · moved ${HELD} C → IL (dated ${DAY}) · ${SAVED} · opening the claim`);
  const dry = I.ilRun({ item: item(), day: DAY, trigger: "routine", mode: "dry_run", outcome: "would_move", controls });
  assert.equal(I.ilStripText({ run: dry }), `dry run · would move ${HELD} C → IL (dated ${DAY})`);
  const late = I.unreadIL({ day: DAY, entry: ENTRY, player: HELD, slot: "IL", dated: DAY, trigger: "routine", page: "/p" }, "0.9.1");
  assert.deepEqual([late.mode, late.outcome, late.reason, late.entry, late.to_slot, late.dated], ["live", "failed", "clicked; Yahoo's answer was not read", ENTRY, "IL", DAY]);
  // A full roster after a move dated tomorrow: the claim waits; any other skip stands.
  const full = { outcome: "skipped", reason: `the roster is full: ${HELD} to IL first (the page lists 11 to drop)` };
  const moved = (dated) => ({ day: DAY, dated, logged: true, run: { outcome: "moved" } });
  assert.deepEqual(I.claimWaits(full, moved("2026-10-28"), DAY), { outcome: "skipped", reason: "move dated 2026-10-28, claim waits" });
  assert.equal(I.claimWaits(full, moved(DAY), DAY), full);
  assert.equal(I.claimWaits(full, null, DAY), full);
  assert.equal(I.claimWaits(full, { ...moved("2026-10-28"), run: { outcome: "failed" } }, DAY), full);
  const other = { outcome: "skipped", reason: "the page shows no waiver date" };
  assert.equal(I.claimWaits(other, moved("2026-10-28"), DAY), other);
  assert.equal(I.claimWaits({ outcome: "would_claim", reason: "open spot" }, moved("2026-10-28"), DAY).outcome, "would_claim");
});

// ---------------------------------------------------------------- the two clicks on a fake page
/** My team page's swap as step 0 read it and today's markup shows: every row ``tr.editable``, a
 * slot label ``span.pos-label[data-pos][role=button]``, the empty IL row's two labels hidden. A
 * click on the held player's label starts the swap and shows ``shows`` of the empty IL row's labels
 * (0: none); a click on a shown one saves ``after`` looks later (a look is one ``wait``): the
 * notice reads ``answer`` (``saved`` "All changes saved", ``error`` Yahoo's error, null nothing)
 * and the player's label reads IL. ``alert`` is an alert Yahoo raises on the first click. Clicks
 * go in ``touched``. */
function ilDom({ held = "C", editable = true, shows = 1, answer = "saved", after = 2, alert = null, stale = false } = {}) {
  const touched = [];
  const attrs = {};
  let looks = null;
  const label = (pos, visible, onClick) => {
    const l = {
      visible,
      getAttribute: (a) => ({ "data-pos": pos, role: "button" })[a] ?? null,
      getClientRects: () => (l.visible ? [{}] : []),
      click: () => onClick(l),
    };
    return l;
  };
  const row = (classes, player, labels) => ({
    player,
    labels,
    classList: { contains: (c) => classes.split(" ").includes(c) },
    querySelector: (sel) => (sel === "[data-ys-playerid]" && row_(player) ? { getAttribute: () => String(player) } : null),
    querySelectorAll: (sel) => (sel === I.IL_LABEL ? labels : []),
  });
  const row_ = (p) => p != null;
  const notices = stale ? [{ className: "rostersave-msg saved", textContent: SAVED, getClientRects: () => [{}] }] : [];
  let heldLabel;
  const ilLabels = [0, 1].map((k) =>
    label("IL", false, () => {
      touched.push(`click IL ${k}`);
      looks = 0;
    }),
  );
  heldLabel = label(held, true, () => {
    touched.push("click held");
    if (alert) attrs["data-pickandroll-alerts"] = JSON.stringify([alert]);
    ilLabels.slice(0, shows).forEach((l) => (l.visible = true));
  });
  let heldPos = held;
  heldLabel.getAttribute = (a) => ({ "data-pos": heldPos, role: "button" })[a] ?? null;
  const rows = [
    row("First editable", 5767, [label("PG", true, () => touched.push("click PG"))]),
    row(`bench bench${editable ? " editable" : ""}`, HELD, [heldLabel]),
    row("bench bench empty-bench editable", null, [label("BN", false, () => touched.push("click BN")), label("BN", false, () => touched.push("click BN"))]),
    row("bench bench empty-bench editable", null, ilLabels),
  ];
  return {
    touched,
    look() {
      if (looks === null) return;
      looks += 1;
      if (looks !== after || !answer) return;
      if (answer === "saved") {
        notices.splice(0, notices.length, { className: "rostersave-msg saved", textContent: ` ${SAVED} `, getClientRects: () => [{}] });
        heldPos = "IL";
      } else notices.splice(0, notices.length, { className: "rostersave-msg error", textContent: "There was an error saving your changes.", getClientRects: () => [{}] });
    },
    querySelectorAll: (sel) => (sel === I.IL_ROWS ? rows : sel === I.IL_SAVED ? notices.map((n) => ({ ...n, classList: { contains: (c) => n.className.split(" ").includes(c) } })) : []),
    querySelector: (sel) => (sel === I.IL_MANAGER ? { getAttribute: (a) => (a === "data-is-editable" ? "true" : null) } : null),
    documentElement: { getAttribute: (a) => attrs[a] ?? null, setAttribute: (a, v) => (attrs[a] = v) },
    raw() {
      return {
        path: `/nba/${LEAGUE}/${TEAM}?date=${DAY}`,
        editable: true,
        rows: rows.map((r) => ({
          player: r.player,
          editable: r.classList.contains("editable"),
          empty: r.classList.contains("empty-bench"),
          labels: r.labels.map((l) => ({ pos: l.getAttribute("data-pos"), button: true, visible: l.getClientRects().length > 0 })),
        })),
      };
    },
  };
}
const move = (dom, opts = {}, it = item()) => I.moveToIL(dom, it, { wait: async () => dom.look(), every: 200, ...opts });

test("the move: the player's label, then the empty IL row's once the swap shows it, then Yahoo's save", async () => {
  const dom = ilDom();
  assert.deepEqual(I.readILPage(dom.raw(), item()).from_slot, "C");
  const got = await move(dom);
  assert.deepEqual(got, { outcome: "moved", reason: null, message: SAVED });
  assert.deepEqual(dom.touched, ["click held", "click IL 0"]);
  // A "saved" notice already on the page before the move does not stand for this one.
  const stale = ilDom({ stale: true, answer: null });
  const late = await move(stale, { saveCap: 1000 });
  assert.deepEqual([late.outcome, late.reason], ["failed", "clicked; the save was not read in 1 s"]);
});

test("the move stops where the page does not answer as step 0 read it", async () => {
  // Nothing clicked: the player's row not editable, or on IL already.
  for (const over of [{ editable: false }, { held: "IL" }]) {
    const dom = ilDom(over);
    const got = await move(dom);
    assert.deepEqual([got.outcome, dom.touched], ["skipped", []], JSON.stringify(over));
  }
  // The swap never shows one IL label (none, or both): one click, nothing saved.
  for (const shows of [0, 2]) {
    const dom = ilDom({ shows });
    const got = await move(dom, { showCap: 1000 });
    assert.deepEqual([got.outcome, got.reason, dom.touched], ["failed", "the IL slot did not show within 1 s (nothing saved)", ["click held"]]);
  }
  // Yahoo's error, its alert, no answer.
  let dom = ilDom({ answer: "error" });
  let got = await move(dom);
  assert.deepEqual([got.outcome, got.reason, got.message, dom.touched], ["failed", "Yahoo did not save the move", "There was an error saving your changes.", ["click held", "click IL 0"]]);
  dom = ilDom({ alert: "This player cannot be moved." });
  got = await move(dom);
  assert.deepEqual([got.outcome, got.reason, dom.touched], ["failed", `Yahoo answered the first click: "This player cannot be moved."`, ["click held"]]);
  dom = ilDom({ answer: null });
  got = await move(dom, { saveCap: 1000 });
  assert.deepEqual([got.outcome, dom.touched], ["failed", ["click held", "click IL 0"]]);
  // IL+ wanted, only IL rows: nothing shows for it.
  dom = ilDom();
  got = await move(dom, { showCap: 1000 }, item({ slot: "IL+" }));
  assert.deepEqual([got.outcome, dom.touched], ["failed", ["click held"]]);
});

test("only moveToIL clicks among the IL code: two clicks, no field set, nothing fetched", () => {
  const moved = I.moveToIL.toString();
  const src = fs.readFileSync(path.join(DIR, "lib/ilmove.js"), "utf8").replace(moved, "");
  assert.ok(!/\.click\(|dispatchEvent|submit\(|requestSubmit/.test(src), "lib/ilmove.js clicks outside moveToIL");
  assert.ok(!/\.(value|selectedIndex|checked)\s*=[^=]/.test(src));
  assert.equal(moved.match(/\.click\(\)/g).length, 2, "the player's label and the IL row's");
  assert.ok(!/\.(value|checked|selectedIndex)\s*=[^=]|dispatchEvent|submit\(|fetch\(|XMLHttpRequest|crumb|roster-save-btn|select/.test(moved));
  assert.ok(!/\bfetch\(|XMLHttpRequest|DOMParser/.test(fs.readFileSync(path.join(DIR, "lib/ilmove.js"), "utf8")));
});

test("the alert recorder: also on a team page opened with an IL fragment", () => {
  const R = require("../addpage.js");
  assert.deepEqual([...R.IL_FRAGMENTS].sort(), Object.keys(I.IL_TRIGGERS).sort());
  const installed = (pathname, hash) => {
    const attrs = {};
    return R.install({ location: { pathname, hash }, alert() {}, document: { documentElement: { getAttribute: (a) => attrs[a] ?? null, setAttribute: (a, v) => (attrs[a] = v) } } });
  };
  for (const hash of Object.keys(I.IL_TRIGGERS)) assert.equal(installed(`/nba/${LEAGUE}/${TEAM}`, `#${hash}`), true);
  assert.equal(installed(`/nba/${LEAGUE}/addplayer`, "#pickandroll-il"), false);
  assert.equal(installed(`/nba/${LEAGUE}/${TEAM}`, ""), false);
});

// ---------------------------------------------------------------- the content script
/** league.js on my team page of ``date`` (``hash`` its fragment) over ``dom``, a chrome whose
 * worker answers each op with ``answer``. Returns the messages sent, the URLs replaced and
 * assigned, the strip and the clicks. */
async function visitTeam({ hash = "#pickandroll-il", answer, dom = ilDom(), date = DAY }) {
  const nodes = {};
  const doc = {
    ...dom,
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
  const url = new URL(`${SITE}/nba/${LEAGUE}/${TEAM}?date=${date}${hash}`);
  const assigned = [];
  const location = { href: url.href, hash: url.hash, pathname: url.pathname, search: url.search, origin: url.origin, assign: (u) => assigned.push(u) };
  const sent = [];
  const replaced = [];
  const timers = [];
  const chrome = {
    runtime: {
      connect: () => ({}),
      getManifest: () => ({ version: "0.9.1" }),
      onMessage: { addListener() {} },
      sendMessage: async (msg) => {
        sent.push({ ...JSON.parse(JSON.stringify(msg)), clicks: dom.touched.length });
        return answer(msg, sent);
      },
    },
  };
  // The move's waits run at once, each a look.
  const ctx = vm.createContext({
    chrome,
    location,
    document: doc,
    history: { replaceState: (_s, _t, u) => replaced.push(u) },
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
  for (const file of ["lib/league.js", "lib/lineup.js", "lib/moves.js", "lib/startactive.js", "lib/ilmove.js", "league.js"]) vm.runInContext(fs.readFileSync(path.join(DIR, file), "utf8"), ctx);
  ctx.started = true;
  for (const fn of timers.splice(0)) await fn();
  return { sent, replaced, assigned, strip: nodes["pickandroll-strip"], touched: dom.touched };
}

const worker =
  (d = due(), { settings = {}, record = null, kept = true, log = true } = {}) =>
  (msg) => {
    if (msg.op === "settings") return { ok: true, data: { lineup_executor: "on", moves_executor: "on", ...settings } };
    if (msg.op === "season_page") return { ok: true, data: { post: { accepted: [`team/${TEAM}`] }, follow: null } };
    if (msg.op === "moves_landed") return { ok: true, data: null };
    if (msg.op === "moves_due") return { ok: true, data: d };
    if (msg.op === "il_record") return { ok: true, data: record };
    if (msg.op === "il_moving") return kept ? { ok: true, data: { kept: true } } : { ok: false, error: "this move awaits its log" };
    if (msg.op === "il_log") return log ? { ok: true, data: { at: "x" } } : { ok: false, error: "STOP is on: a run can only say it stopped" };
    return { ok: false, error: `unexpected ${msg.op}` };
  };
const ops = (v) => v.sent.map((m) => m.op);
const logOf = (v) => v.sent.filter((m) => m.op === "il_log");
const RUN = ["moves_landed", "settings", "season_page", "moves_due", "il_record"];
const CLAIM = `${SITE}/nba/${LEAGUE}/addplayer?apid=${ADD}#pickandroll-moves`;

test("a dry run: would_move logged, nothing clicked, then the claim's add page", async () => {
  const v = await visitTeam({ answer: worker() });
  assert.deepEqual(v.replaced, [`/nba/${LEAGUE}/${TEAM}?date=${DAY}`]);
  assert.deepEqual(ops(v), [...RUN, "il_log"]);
  assert.deepEqual(v.touched, []);
  const { run, clicked, release } = logOf(v)[0];
  assert.deepEqual([run.mode, run.trigger, run.outcome, run.entry, run.player, run.from_slot, run.to_slot, run.dated, run.extension, clicked, release], ["dry_run", "routine", "would_move", ENTRY, HELD, "C", "IL", DAY, "0.9.1", false, false]);
  assert.deepEqual(v.assigned, [CLAIM]);
  assert.equal(v.strip.textContent, `pickandroll IL move: dry run · would move ${HELD} C → IL (dated ${DAY}) · opening the claim`);
  // A live league whose guard refuses runs dry, with why.
  const r = await visitTeam({ answer: worker(due({ mode: "live", live: { ok: false, reason: "a dry run on 7 days first" } })) });
  assert.deepEqual([logOf(r)[0].run.outcome, logOf(r)[0].run.reason, r.touched], ["would_move", "live refused: a dry run on 7 days first", []]);
});

test("a live move: on record before any click, the two clicks, moved logged, then the claim", async () => {
  const v = await visitTeam({ hash: "#pickandroll-il-evening", answer: worker(due(LIVE)) });
  assert.deepEqual(ops(v), [...RUN, "il_moving", "il_log"]);
  const put = v.sent.find((m) => m.op === "il_moving");
  assert.equal(put.clicks, 0, "on record before any click");
  assert.deepEqual(put.record, { day: DAY, entry: ENTRY, player: HELD, slot: "IL", dated: DAY, trigger: "routine_evening", page: `/nba/${LEAGUE}/${TEAM}?date=${DAY}` });
  assert.deepEqual(v.touched, ["click held", "click IL 0"]);
  const { run, clicked, release } = logOf(v)[0];
  assert.deepEqual([run.mode, run.outcome, run.message, clicked, release], ["live", "moved", SAVED, true, false]);
  assert.deepEqual(v.assigned, [`${SITE}/nba/${LEAGUE}/addplayer?apid=${ADD}#pickandroll-moves-evening`]);
  // A failed move is logged and the claim's page still opens (it reads the full roster).
  const f = await visitTeam({ answer: worker(due(LIVE)), dom: ilDom({ answer: "error" }) });
  assert.deepEqual([logOf(f)[0].run.outcome, f.assigned], ["failed", [CLAIM]]);
});

test("a live move clicks nothing when it may not, and a stop or an unlogged run opens no claim", async () => {
  // No item for this page: nothing logged, nowhere to go.
  let v = await visitTeam({ answer: worker(due(LIVE, [])) });
  assert.deepEqual([ops(v), v.touched, v.assigned], [RUN.slice(0, 4), [], []]);
  assert.equal(v.strip.textContent, "pickandroll IL move: no IL move due on this page");
  // Another date's page: not the item's.
  v = await visitTeam({ answer: worker(due(LIVE)), date: "2026-10-28" });
  assert.deepEqual([logOf(v).length, v.touched], [0, []]);
  // STOP: the run says it stopped and the tab stays.
  v = await visitTeam({ answer: worker(due({ ...LIVE, stop: true, reason: "STOP is on (data/autopilot/STOP)" })) });
  assert.deepEqual([logOf(v)[0].run.outcome, logOf(v)[0].run.entry, v.touched, v.assigned], ["stopped", null, [], []]);
  // Off in the league, or in this browser: nothing.
  v = await visitTeam({ answer: worker(due({ mode: "off" })) });
  assert.deepEqual([logOf(v).length, v.assigned], [0, []]);
  v = await visitTeam({ answer: worker(due(LIVE), { settings: { moves_executor: "off" } }) });
  assert.deepEqual([ops(v), v.touched], [["moves_landed", "settings"], []]);
  // The page fails a check: skipped, no record asked for, the claim still opens.
  v = await visitTeam({ answer: worker(due(LIVE)), dom: ilDom({ editable: false }) });
  assert.deepEqual([logOf(v)[0].run.outcome, logOf(v)[0].run.reason, v.touched, ops(v).includes("il_moving"), v.assigned], ["skipped", "the player's slot is locked on this page", [], false, [CLAIM]]);
  // Made from this browser today: never again.
  v = await visitTeam({ answer: worker(due(LIVE), { record: { day: DAY, entry: ENTRY, logged: true, at: Date.now() - 3600e3, run: { outcome: "moved" } } }) });
  assert.deepEqual([logOf(v)[0].run.reason, v.touched], ["this move was made from this browser today", []]);
  // The worker refuses the record: nothing clicked.
  v = await visitTeam({ answer: worker(due(LIVE), { kept: false }) });
  assert.deepEqual([logOf(v)[0].run.reason, v.touched], ["the move could not be put on record: this move awaits its log", []]);
  // The log refuses the run: the strip says so and the tab stays.
  v = await visitTeam({ answer: worker(due(), { log: false }) });
  assert.deepEqual(v.assigned, []);
  assert.match(v.strip.textContent, /not logged: STOP is on/);
});

test("a move whose run never reached the log is logged first; a plain visit runs nothing", async () => {
  const stale = { day: DAY, entry: ENTRY, player: HELD, slot: "IL", dated: DAY, trigger: "routine", page: `/nba/${LEAGUE}/${TEAM}?date=${DAY}`, logged: false, at: Date.now() - I.IL_UNREAD_MS - 1 };
  const v = await visitTeam({ answer: worker(due(LIVE), { record: stale }) });
  const [late, now] = logOf(v);
  assert.deepEqual([late.run.outcome, late.run.reason, late.clicked], ["failed", "clicked; Yahoo's answer was not read", true]);
  assert.deepEqual([now.run.outcome, v.touched], ["skipped", []]);
  const p = await visitTeam({ hash: "", answer: worker(due(LIVE)) });
  assert.ok(!ops(p).some((o) => o.startsWith("il_") || o === "moves_due"));
  assert.deepEqual([p.touched, p.assigned], [[], []]);
});

// ---------------------------------------------------------------- the worker's record of a move
function loadWorker(reply) {
  const listeners = [];
  const fetches = [];
  const local = new Map([["api", "http://api.test"]]);
  const area = (m) => ({
    get: async (keys) => {
      const want = keys == null ? [...m.keys()] : Array.isArray(keys) ? keys : [keys];
      return Object.fromEntries(want.filter((k) => m.has(k)).map((k) => [k, structuredClone(m.get(k))]));
    },
    set: async (obj) => {
      for (const [k, v] of Object.entries(obj)) m.set(k, structuredClone(v));
    },
    remove: async (keys) => {
      for (const k of Array.isArray(keys) ? keys : [keys]) m.delete(k);
    },
  });
  const evt = (list) => ({ addListener: (fn) => list.push(fn) });
  const chrome = {
    runtime: { onMessage: evt(listeners), onConnect: evt([]), onInstalled: evt([]), onStartup: evt([]) },
    storage: { local: area(local), session: area(new Map()) },
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
  const send = (msg, tab = 7) =>
    new Promise((resolve) => {
      const done = (r) => resolve(JSON.parse(JSON.stringify(r)));
      for (const fn of listeners) if (fn(msg, { tab: { id: tab } }, done) === true) return;
      resolve(undefined);
    });
  return { send, fetches, local };
}

test("the worker: one move on record per entry and day, kept until the API has it, given back when never made", async () => {
  let status = 200;
  const w = loadWorker(() => [status, status < 400 ? { at: "x" } : { detail: `${ENTRY}'s IL move failed today: it is never retried that day` }]);
  const key = `il_move:${ENTRY}`;
  const record = { day: DAY, entry: ENTRY, player: HELD, slot: "IL", dated: DAY, trigger: "routine", page: "/p" };
  assert.equal((await w.send({ op: "il_record", entry: ENTRY })).data, null);
  assert.deepEqual(await w.send({ op: "il_moving", league: LEAGUE, record }), { ok: true, data: { kept: true } });
  assert.deepEqual([w.local.get(key).logged, w.local.get(key).tab], [false, 7]);
  assert.equal((await w.send({ op: "il_moving", league: LEAGUE, record }, 8)).error, "this move awaits its log");
  // A move never made gives the record back (none before it: gone).
  await w.send({ op: "il_log", league: LEAGUE, run: { day: DAY, entry: ENTRY, mode: "live", outcome: "skipped" }, release: true });
  assert.equal(w.local.has(key), false);
  // Made and logged: kept, and never made again that day.
  assert.equal((await w.send({ op: "il_moving", league: LEAGUE, record })).ok, true);
  const run = { day: DAY, entry: ENTRY, mode: "live", trigger: "routine", outcome: "moved", message: SAVED };
  assert.equal((await w.send({ op: "il_log", league: LEAGUE, run, clicked: true })).ok, true);
  assert.equal(w.fetches.at(-1).url, `http://api.test/seasons/${LEAGUE}/autopilot/il`);
  assert.deepEqual([w.local.get(key).logged, w.local.get(key).run.outcome], [true, "moved"]);
  assert.equal((await w.send({ op: "il_moving", league: LEAGUE, record })).error, "this move was made already today");
  // A failed log keeps it open with its run; a refusal closes it.
  const other = `${DAY}:${LEAGUE}:6039:0`;
  assert.equal((await w.send({ op: "il_moving", league: LEAGUE, record: { ...record, entry: other } })).ok, true);
  status = 503;
  assert.equal((await w.send({ op: "il_log", league: LEAGUE, run: { ...run, entry: other }, clicked: true })).ok, false);
  assert.equal(w.local.get(`il_move:${other}`).logged, false);
  status = 409;
  assert.equal((await w.send({ op: "il_log", league: LEAGUE, run: { ...run, entry: other }, clicked: true })).ok, false);
  assert.match(w.local.get(`il_move:${other}`).refused, /never retried/);
  // A dry run's log, or a stop's, never touches a record.
  status = 200;
  assert.equal((await w.send({ op: "il_log", league: LEAGUE, run: { day: DAY, entry: null, mode: "live", outcome: "stopped" } })).ok, true);
});
