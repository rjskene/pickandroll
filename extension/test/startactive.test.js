// node --test extension/test/*.test.js
// Yahoo's Start Active Players for the rest of the week (#215, ext 0.9.0): the dialog's words read,
// the page checks, the same-day rule, the two presses on a fake team page built from step 0's read
// (#214, 2026-10-27), the content script on a team page opened with a start-active fragment, the
// alert recorder there, and the worker's record of a press. Nothing here reaches Yahoo. Fixtures
// carry Yahoo ids and Yahoo's own words only.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const S = require("../lib/startactive.js");

const DIR = path.join(__dirname, "..");
const SITE = "https://basketball.fantasysports.yahoo.com";
const LEAGUE = "100001";
const TEAM = 7;
const DAY = "2026-10-27";
const ROSTER = { players: [2001, 2002, 2003, 2004], held: [2004] };

// The dialog's text as step 0 read it, before and after the main press, and Yahoo's answer.
const HEAD = "Start Active Players Set roster lineups with players scheduled to play. Learn More ";
const ROWS = "Today Only Tue, Oct 27 Rest of Week 2 Tue, Oct 27 - Sun, Nov 01 Start Unlock multi-week lineup optimizations";
const UPDATED = "6 lineups updated";

/** The due route's row of the league (GET /autopilot/start-active/due). */
const row = (over = {}) => ({
  league: LEAGUE,
  mode: "dry_run",
  need: true,
  reasons: ["week_start"],
  team: TEAM,
  week: { start: "2026-10-26", end: "2026-11-01" },
  roster: ROSTER,
  page: `/nba/${LEAGUE}/${TEAM}?date=${DAY}`,
  live: { ok: false, reason: "the league is not live" },
  ...over,
});
const LIVE = { mode: "live", live: { ok: true, reason: null } };
const due = (over = {}, extra = {}) => ({ date: DAY, stop: false, reason: null, leagues: [row(over)], at: `${DAY}T10:00:00Z`, ...extra });

test("the triggers, the dialog's rows and Yahoo's words", () => {
  assert.equal(S.startActiveTriggerOf("#pickandroll-start-active"), "routine");
  assert.equal(S.startActiveTriggerOf("#pickandroll-start-active-late"), "routine_late");
  assert.equal(S.startActiveTriggerOf("#pickandroll-start-active-evening"), "routine_evening");
  assert.equal(S.startActiveTriggerOf("#pickandroll-start-active-daily"), "routine_daily");
  assert.equal(S.startActiveTriggerOf("#pickandroll-start-active-panel"), "panel");
  for (const h of ["", "#pickandroll-lineup", "#pickandroll-moves", "#other"]) assert.equal(S.startActiveTriggerOf(h), null);
  assert.deepEqual(S.dialogRows(HEAD + ROWS), {
    today: { label: "Today Only", range: "Tue, Oct 27" },
    rest_of_week: { label: "Rest of Week 2", range: "Tue, Oct 27 - Sun, Nov 01" },
  });
  assert.deepEqual(S.dialogRows(HEAD), { today: null, rest_of_week: null });
  assert.equal(S.yahooAnswer(HEAD + ROWS), null);
  assert.deepEqual(S.yahooAnswer(`${HEAD}${ROWS} ${UPDATED}`), { outcome: "started", message: UPDATED });
  assert.deepEqual(S.yahooAnswer("We optimized your lineups for Rest of Week 2."), { outcome: "started", message: "We optimized your lineups for Rest of Week 2." });
  assert.deepEqual(S.yahooAnswer(`${ROWS} Already optimized`), { outcome: "already", message: "Already optimized" });
  assert.equal(S.yahooAnswer(`${ROWS} An error occurred. Please try again`).outcome, "failed");
  // "N lineups updated" is Yahoo's words, never a count: a repeat says it too (step 0).
  assert.deepEqual(S.yahooAnswer("1 lineup updated"), { outcome: "started", message: "1 lineup updated" });
});

test("the page checks, the mode and the same-day rule", () => {
  const page = { league: LEAGUE, kind: "team", team: TEAM };
  const raw = (over = {}) => ({ path: `/nba/${LEAGUE}/${TEAM}`, buttons: [{ visible: true, disabled: false }], outside: 0, dialog: { present: true, open: false }, intervals: [], ...over });
  const c = S.readStartActive(raw());
  assert.deepEqual(c, { path: `/nba/${LEAGUE}/${TEAM}`, buttons: 1, outside: 0, visible: true, disabled: false, dialog: true, open: false, intervals: 0 });
  assert.equal(S.startActiveProblem(row(), page, c), null);
  assert.equal(S.startActiveProblem(row(), { ...page, team: 3 }, c), "not my team's page");
  assert.equal(S.startActiveProblem(row(), { league: LEAGUE, kind: "players" }, c), "not a team page");
  assert.match(S.startActiveProblem(row(), page, S.readStartActive(raw({ buttons: [] }))), /no single Start Active Players button/);
  assert.match(S.startActiveProblem(row(), page, S.readStartActive(raw({ buttons: [{ visible: true }, { visible: true }] }))), /\(2 on the page\)/);
  assert.equal(S.startActiveProblem(row(), page, S.readStartActive(raw({ buttons: [{ visible: false, disabled: false }] }))), "the Start Active Players button is hidden");
  assert.equal(S.startActiveProblem(row(), page, S.readStartActive(raw({ buttons: [{ visible: true, disabled: true }] }))), "the Start Active Players button is disabled");
  assert.equal(S.startActiveProblem(row(), page, S.readStartActive(raw({ dialog: null }))), "the page has no Start Active dialog");
  assert.equal(S.startActiveProblem(row(), page, S.readStartActive(raw({ dialog: { present: true, open: true } }))), "the Start Active dialog was open before the run");

  assert.deepEqual(S.startActiveMode(row()), { mode: "dry_run", reason: null });
  assert.deepEqual(S.startActiveMode(row(LIVE)), { mode: "live", reason: null });
  assert.deepEqual(S.startActiveMode(row({ mode: "live", live: { ok: false, reason: "a dry run on 7 days first" } })), { mode: "dry_run", reason: "live refused: a dry run on 7 days first" });

  // One press a day (ruling on #215): the guard lifts when the page's roster differs from the
  // press's, players or held, or when the need rule says roster_changed / il_moved.
  const record = { day: DAY, roster: ROSTER, logged: true };
  assert.equal(S.sameDayProblem(null, row(), DAY), null);
  assert.equal(S.sameDayProblem({ ...record, day: "2026-10-26" }, row(), DAY), null);
  assert.match(S.sameDayProblem(record, row(), DAY), /ran in this league today/);
  assert.match(S.sameDayProblem(record, row({ reasons: ["no_run"] }), DAY), /roster has not changed/);
  assert.equal(S.sameDayProblem(record, row({ reasons: ["no_run"], roster: { players: [2001, 2002, 2003, 2005], held: [2004] } }), DAY), null);
  assert.equal(S.sameDayProblem(record, row({ reasons: ["no_run"], roster: { players: ROSTER.players, held: [2003, 2004] } }), DAY), null);
  assert.equal(S.sameDayProblem(record, row({ reasons: ["roster_changed"] }), DAY), null);
  assert.equal(S.sameDayProblem(record, row({ reasons: ["il_moved"] }), DAY), null);
  // An unknown roster never lifts it; the same roster in another order is the same roster.
  assert.match(S.sameDayProblem({ ...record, roster: null }, row({ reasons: ["no_run"] }), DAY), /ran in this league today/);
  assert.equal(S.rosterDiffers(ROSTER, { players: [2004, 2003, 2002, 2001], held: [2004] }), false);
});

test("the run the log takes, the strip and the panel's line", () => {
  const run = S.startActiveRun({ row: row(LIVE), day: DAY, trigger: "routine", mode: "live", outcome: "started", message: UPDATED, rest_of_week: { label: "Rest of Week 2", range: "Tue, Oct 27 - Sun, Nov 01" }, page: `/nba/${LEAGUE}/${TEAM}`, extension: "0.9.0" });
  assert.deepEqual(Object.keys(run).sort(), ["controls", "day", "extension", "message", "mode", "outcome", "page", "reason", "reasons", "rest_of_week", "roster", "today", "trigger"]);
  assert.deepEqual(run.reasons, ["week_start"]);
  assert.equal(S.startActiveStripText({ run }), `live · started active players, Rest of Week 2 · ${UPDATED}`);
  const dry = S.startActiveRun({ row: row(), day: DAY, trigger: "routine_daily", mode: "dry_run", outcome: "would_start" });
  assert.equal(S.startActiveStripText({ run: dry }), "dry run · would start active players for the rest of the week");
  assert.equal(S.startActiveStripText({ row: row({ need: false }) }), "not due: nothing pressed");
  assert.equal(S.startActiveStripText({ browserOff: true }), "off in this browser (options page)");
  assert.equal(S.startActiveLastText(null, ""), "no run from this browser yet");
  assert.equal(S.startActiveLastText({ day: DAY, trigger: "routine_daily", mode: "live", outcome: "already", message: "Already optimized" }, "2 min ago"), `${DAY} · daily routine, live: already optimized · Already optimized, 2 min ago`);
  const late = S.unreadRun({ day: DAY, trigger: "routine", reasons: ["no_run"], page: `/nba/${LEAGUE}/${TEAM}` }, "0.9.0");
  assert.deepEqual([late.mode, late.outcome, late.reason, late.reasons, late.roster], ["live", "failed", "pressed; Yahoo's answer was not read", ["no_run"], null]);
  assert.deepEqual(S.unreadRun({ day: DAY, trigger: "routine", reasons: ["no_run"], roster: ROSTER }, "0.9.0").roster, ROSTER);
  assert.deepEqual(run.roster, ROSTER);
});

// ---------------------------------------------------------------- the presses on a fake page
/** Yahoo's Start Active control on a fake team page, as step 0 read it: a click on the main
 * button runs Today Only and opens the dialog, which lists the Rest of Week row with its Start
 * (``rows``: "show", "none" never, "error" Today Only's error); a click on that Start answers
 * ``answer`` ``after`` looks later (a look is one ``wait``; null: never) and the dialog closes,
 * its text staying. ``buttons`` the count in Yahoo's root, ``disabled`` the main button's,
 * ``open`` the dialog open before the run, ``startDisabled`` the Rest of Week Start's,
 * ``alert`` an alert Yahoo raises on the main press (kept by the recorder). Clicks go in
 * ``touched``. */
function saDom({ buttons = 1, outside = 0, disabled = false, visible = true, open = false, dialog: hasDialog = true, rows = "show", answer = UPDATED, after = 2, startDisabled = false, alert = null } = {}) {
  const touched = [];
  const attrs = {};
  let looks = null;
  const start = {
    disabled: startDisabled,
    click() {
      touched.push("click start");
      looks = 0;
    },
  };
  const dialog = {
    open,
    textContent: HEAD,
    querySelectorAll: (sel) => (sel === S.SA_INTERVAL && dialog.textContent.includes("Rest of Week") ? [start] : []),
  };
  const button = () => ({
    disabled,
    getClientRects: () => (visible ? [{}] : []),
    click() {
      touched.push("click main");
      if (alert) attrs["data-pickandroll-alerts"] = JSON.stringify([alert]);
      dialog.open = true;
      if (rows === "show") dialog.textContent = HEAD + ROWS;
      if (rows === "error") dialog.textContent = `${HEAD} An error occurred. Please try again`;
    },
  });
  const inside = Array.from({ length: buttons }, button);
  const rest = Array.from({ length: outside }, button);
  return {
    touched,
    dialog,
    look() {
      if (looks === null) return;
      looks += 1;
      if (answer && looks === after) {
        dialog.textContent += ` ${answer}`;
        dialog.open = false;
      }
    },
    querySelectorAll: (sel) => (sel === `${S.SA_OVERLAY} ${S.SA_BUTTON}` ? inside : sel === S.SA_BUTTON ? [...inside, ...rest] : []),
    querySelector: (sel) => (sel === S.SA_DIALOG && hasDialog ? dialog : null),
    documentElement: { getAttribute: (a) => attrs[a] ?? null, setAttribute: (a, v) => (attrs[a] = v) },
  };
}
const press = (dom, opts = {}) => S.pressStartActive(dom, { wait: async () => dom.look(), every: 200, ...opts });

test("the presses: the main button, then the Rest of Week Start once the dialog lists it, then Yahoo's words", async () => {
  let dom = saDom();
  let got = await press(dom);
  assert.deepEqual(dom.touched, ["click main", "click start"]);
  assert.deepEqual(got, {
    outcome: "started",
    reason: null,
    message: UPDATED,
    today: { label: "Today Only", range: "Tue, Oct 27" },
    rest_of_week: { label: "Rest of Week 2", range: "Tue, Oct 27 - Sun, Nov 01" },
  });
  dom = saDom({ answer: "Already optimized" });
  got = await press(dom);
  assert.deepEqual([got.outcome, got.message], ["already", "Already optimized"]);
  dom = saDom({ answer: "An error occurred. Please try again" });
  got = await press(dom);
  assert.deepEqual([got.outcome, dom.touched], ["failed", ["click main", "click start"]]);
});

test("the presses stop where the page does not answer as step 0 read it", async () => {
  // Nothing pressed: no single button, a disabled one, no dialog, the dialog open already.
  for (const over of [{ buttons: 0 }, { buttons: 2 }, { disabled: true }, { dialog: false }, { open: true }]) {
    const dom = saDom(over);
    const got = await press(dom);
    assert.deepEqual([got.outcome, dom.touched], ["skipped", []], JSON.stringify(over));
  }
  // Today Only ran but the Rest of Week row never shows, or its Start stays disabled: one press.
  for (const over of [{ rows: "none" }, { startDisabled: true }]) {
    const dom = saDom(over);
    const got = await press(dom, { rowsCap: 1000 });
    assert.deepEqual([got.outcome, got.reason, dom.touched], ["failed", "the Rest of Week row did not show within 1 s (Today Only ran)", ["click main"]]);
  }
  let dom = saDom({ rows: "error" });
  let got = await press(dom, { rowsCap: 1000 });
  assert.deepEqual([got.outcome, got.reason, dom.touched], ["failed", "Yahoo's Today Only failed", ["click main"]]);
  // Yahoo alerts on the main press: logged with its words, no second press.
  dom = saDom({ alert: "Your lineup cannot be changed." });
  got = await press(dom);
  assert.deepEqual([got.outcome, got.reason, dom.touched], ["failed", `Yahoo answered the main press: "Your lineup cannot be changed."`, ["click main"]]);
  // Pressed, no answer: failed, never pressed again.
  dom = saDom({ answer: null });
  got = await press(dom, { answerCap: 1000 });
  assert.deepEqual([got.outcome, got.reason, dom.touched], ["failed", "pressed; no answer read in 1 s", ["click main", "click start"]]);
});

test("only pressStartActive touches a page: two clicks, no field set, nothing fetched", () => {
  const pressed = S.pressStartActive.toString();
  for (const f of ["lib/startactive.js", "league.js", "addpage.js", "worker.js"]) {
    const src = fs.readFileSync(path.join(DIR, f), "utf8").replace(pressed, "").replace(require("../lib/moves.js").fillClaim.toString(), "");
    assert.ok(!/\.click\(|dispatchEvent|submit\(|requestSubmit/.test(src), `${f} clicks or submits outside the two presses`);
    assert.ok(!/\.(value|selectedIndex|checked)\s*=[^=]/.test(src), `${f} sets a field`);
  }
  assert.equal(pressed.match(/\.click\(\)/g).length, 2, "the main button and the Rest of Week Start");
  assert.ok(!/\.(value|checked|selectedIndex)\s*=[^=]|dispatchEvent|submit\(|fetch\(|XMLHttpRequest|crumb/.test(pressed));
  assert.ok(!/\bfetch\(|XMLHttpRequest|DOMParser/.test(fs.readFileSync(path.join(DIR, "lib/startactive.js"), "utf8")));
});

test("the alert recorder: also on a team page opened with a start-active fragment", () => {
  const R = require("../addpage.js");
  assert.deepEqual([...R.START_ACTIVE_FRAGMENTS].sort(), Object.keys(S.START_ACTIVE_TRIGGERS).sort());
  const page = (pathname, hash) => {
    const attrs = {};
    const win = { location: { pathname, hash }, alert() {}, document: { documentElement: { getAttribute: (a) => attrs[a] ?? null, setAttribute: (a, v) => (attrs[a] = v) } } };
    return R.install(win);
  };
  for (const hash of Object.keys(S.START_ACTIVE_TRIGGERS)) assert.equal(page(`/nba/${LEAGUE}/${TEAM}`, `#${hash}`), true);
  assert.equal(page(`/nba/${LEAGUE}/${TEAM}`, ""), false);
  assert.equal(page(`/nba/${LEAGUE}/${TEAM}`, "#pickandroll-lineup"), false);
  assert.equal(page(`/nba/${LEAGUE}/addplayer`, "#pickandroll-start-active"), false);
  assert.equal(page(`/nba/${LEAGUE}/players`, "#pickandroll-start-active"), false);
});

// ---------------------------------------------------------------- the content script
/** league.js on my team page (``hash`` its fragment) over ``dom``, a chrome whose worker answers
 * each op with ``answer``. Returns the messages sent, the URLs replaced, the strip and the
 * clicks. */
async function visitTeam({ hash = "#pickandroll-start-active", answer, dom = saDom(), team = TEAM }) {
  const nodes = {};
  const doc = {
    ...dom,
    querySelectorAll: (sel) => dom.querySelectorAll(sel),
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
  const url = new URL(`${SITE}/nba/${LEAGUE}/${team}${hash}`);
  const location = { href: url.href, hash: url.hash, pathname: url.pathname, search: url.search, assign() {} };
  const sent = [];
  const replaced = [];
  const timers = [];
  const chrome = {
    runtime: {
      connect: () => ({}),
      getManifest: () => ({ version: "0.9.0" }),
      onMessage: { addListener() {} },
      sendMessage: async (msg) => {
        sent.push({ ...JSON.parse(JSON.stringify(msg)), clicks: dom.touched.length });
        return answer(msg, sent);
      },
    },
  };
  // The presses' waits run at once, each a look.
  const ctx = vm.createContext({
    chrome,
    location,
    document: doc,
    history: { replaceState: (_s, _t, u) => replaced.push(u) },
    setTimeout: (fn) => {
      if (timers.length === 0 && !ctx.started) timers.push(fn);
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
  for (const file of ["lib/league.js", "lib/lineup.js", "lib/moves.js", "lib/startactive.js", "league.js"]) vm.runInContext(fs.readFileSync(path.join(DIR, file), "utf8"), ctx);
  ctx.started = true;
  for (const fn of timers.splice(0)) await fn();
  return { sent, replaced, strip: nodes["pickandroll-strip"], touched: dom.touched };
}

/** The worker's answers: the settings, the post, the press on record (``record``), the due
 * route, the press put on record (``kept``) and the log. */
const worker =
  (d = due(), { settings = {}, record = null, kept = true } = {}) =>
  (msg) => {
    if (msg.op === "settings") return { ok: true, data: { lineup_executor: "on", moves_executor: "on", ...settings } };
    if (msg.op === "season_page") return { ok: true, data: { post: { accepted: [`team/${TEAM}`] }, follow: null } };
    if (msg.op === "moves_landed") return { ok: true, data: null };
    if (msg.op === "start_active_record") return { ok: true, data: record };
    if (msg.op === "start_active_due") return { ok: true, data: d };
    if (msg.op === "start_active_pressing") return kept ? { ok: true, data: { kept: true } } : { ok: false, error: "a press in this league awaits its log" };
    if (msg.op === "start_active_log") return { ok: true, data: { at: "x" } };
    return { ok: false, error: `unexpected ${msg.op}` };
  };
const ops = (v) => v.sent.map((m) => m.op);
const logOf = (v) => v.sent.filter((m) => m.op === "start_active_log");
const RUN = ["moves_landed", "settings", "season_page", "start_active_record", "start_active_due"];

test("a dry run: the fragment dropped, the page posted, the due read and would_start logged; nothing pressed", async () => {
  const v = await visitTeam({ answer: worker() });
  assert.deepEqual(v.replaced, [`/nba/${LEAGUE}/${TEAM}`]);
  assert.deepEqual(ops(v), [...RUN, "start_active_log"]);
  assert.deepEqual(v.touched, []);
  const { run, pressed, release } = logOf(v)[0];
  assert.deepEqual([run.mode, run.trigger, run.outcome, run.reasons, run.extension, pressed, release], ["dry_run", "routine", "would_start", ["week_start"], "0.9.0", false, false]);
  assert.equal(run.controls.buttons, 1);
  assert.equal(v.strip.textContent, "pickandroll start active: dry run · would start active players for the rest of the week");
  // A live league whose guard refuses runs dry, with why.
  const r = await visitTeam({ answer: worker(due({ mode: "live", live: { ok: false, reason: "a dry run on 7 days first" } })) });
  assert.deepEqual([logOf(r)[0].run.outcome, logOf(r)[0].run.reason, r.touched], ["would_start", "live refused: a dry run on 7 days first", []]);
});

test("a live run: the press on record before the page is touched, two presses, Yahoo's words logged", async () => {
  const v = await visitTeam({ hash: "#pickandroll-start-active-daily", answer: worker(due(LIVE)) });
  assert.deepEqual(ops(v), [...RUN, "start_active_pressing", "start_active_log"]);
  const put = v.sent.find((m) => m.op === "start_active_pressing");
  assert.equal(put.clicks, 0, "on record before any click");
  assert.deepEqual(put.record, { day: DAY, trigger: "routine_daily", reasons: ["week_start"], roster: ROSTER, page: `/nba/${LEAGUE}/${TEAM}` });
  assert.deepEqual(v.touched, ["click main", "click start"]);
  const { run, pressed, release } = logOf(v)[0];
  assert.deepEqual([run.mode, run.trigger, run.outcome, run.message, pressed, release], ["live", "routine_daily", "started", UPDATED, true, false]);
  assert.deepEqual(run.rest_of_week, { label: "Rest of Week 2", range: "Tue, Oct 27 - Sun, Nov 01" });
  assert.equal(v.strip.textContent, `pickandroll start active: live · started active players, Rest of Week 2 · ${UPDATED}`);
});

test("a live run presses nothing when it may not: not due, STOP, the same day, the record refused, a page that fails a check", async () => {
  // Not due: the strip says so, nothing is logged.
  let v = await visitTeam({ answer: worker(due({ ...LIVE, need: false, reasons: [] })) });
  assert.deepEqual([ops(v), v.touched], [RUN, []]);
  assert.equal(v.strip.textContent, "pickandroll start active: not due: nothing pressed");
  // STOP: the run says it stopped.
  v = await visitTeam({ answer: worker(due({ ...LIVE, need: false }, { stop: true, reason: "STOP is on (data/autopilot/STOP)" })) });
  assert.deepEqual([logOf(v)[0].run.outcome, logOf(v)[0].run.mode, v.touched], ["stopped", "live", []]);
  // Pressed today already on this roster: skipped, no record asked for.
  const today = { day: DAY, trigger: "routine", reasons: ["no_run"], roster: ROSTER, logged: true, at: Date.now() - 3600e3 };
  v = await visitTeam({ answer: worker(due(LIVE), { record: today }) });
  assert.deepEqual([ops(v), v.touched], [[...RUN, "start_active_log"], []]);
  assert.match(logOf(v)[0].run.reason, /ran in this league today/);
  // The page's roster differs from the press's: it runs again, with no reason but no_run.
  v = await visitTeam({ answer: worker(due({ ...LIVE, reasons: ["no_run"], roster: { players: [2001, 2002, 2003, 2009], held: [] } }), { record: today }) });
  assert.deepEqual(v.touched, ["click main", "click start"]);
  // The page not taken by the API: its roster is not known, so live presses nothing.
  const unposted = (msg, sent) => (msg.op === "season_page" ? { ok: true, data: { post: { accepted: [], skipped: ["x"] }, follow: null } } : worker(due(LIVE))(msg, sent));
  v = await visitTeam({ answer: unposted });
  assert.deepEqual([logOf(v)[0].run.outcome, logOf(v)[0].run.reason, v.touched], ["skipped", "the page was not posted, so its roster is not known", []]);
  // The worker refuses the record: nothing pressed.
  v = await visitTeam({ answer: worker(due(LIVE), { kept: false }) });
  assert.deepEqual([logOf(v)[0].run.outcome, logOf(v)[0].run.reason, v.touched], ["skipped", "the press could not be put on record: a press in this league awaits its log", []]);
  // Another team's page, a hidden button: skipped before any record.
  v = await visitTeam({ answer: worker(due(LIVE)), team: 3 });
  assert.deepEqual([logOf(v)[0].run.reason, v.touched, ops(v).includes("start_active_pressing")], ["not my team's page", [], false]);
  v = await visitTeam({ answer: worker(due(LIVE)), dom: saDom({ visible: false }) });
  assert.deepEqual([logOf(v)[0].run.reason, v.touched], ["the Start Active Players button is hidden", []]);
  // A button of the same class outside Yahoo's root is never pressed: the one inside is.
  v = await visitTeam({ answer: worker(due(LIVE)), dom: saDom({ outside: 1 }) });
  assert.deepEqual([logOf(v)[0].run.outcome, logOf(v)[0].run.controls.outside, v.touched], ["started", 1, ["click main", "click start"]]);
  // Off in this browser: nothing read, nothing logged.
  v = await visitTeam({ answer: worker(due(LIVE), { settings: { moves_executor: "off" } }) });
  assert.deepEqual([ops(v), v.touched], [["moves_landed", "settings"], []]);
});

test("a press whose run never reached the log is logged first, as read or with its answer not read", async () => {
  const stale = { day: DAY, trigger: "routine", reasons: ["no_run"], roster: ROSTER, page: `/nba/${LEAGUE}/${TEAM}`, logged: false, at: Date.now() - S.SA_UNREAD_MS - 1 };
  let v = await visitTeam({ answer: worker(due(LIVE), { record: stale }) });
  const [late, now] = logOf(v);
  assert.deepEqual([late.run.outcome, late.run.reason, late.run.roster, late.pressed], ["failed", "pressed; Yahoo's answer was not read", ROSTER, true]);
  // The worker answers the same stale record here, so today's run is refused by the same-day rule.
  assert.deepEqual([now.run.outcome, v.touched], ["skipped", []]);
  const read = { ...stale, run: { day: DAY, mode: "live", trigger: "routine", outcome: "started", message: UPDATED } };
  v = await visitTeam({ answer: worker(due(LIVE), { record: read }) });
  assert.deepEqual(logOf(v)[0].run.message, UPDATED);
  // A press in flight in another tab is left alone: the record is asked for and refused.
  const flying = { ...stale, at: Date.now() };
  v = await visitTeam({ answer: worker(due(LIVE), { record: flying, kept: false }) });
  assert.deepEqual([logOf(v).length, logOf(v)[0].run.outcome, v.touched], [1, "skipped", []]);
});

test("a plain visit or another page runs nothing", async () => {
  const v = await visitTeam({ hash: "", answer: worker(due(LIVE)) });
  assert.ok(!ops(v).some((o) => o.startsWith("start_active")));
  assert.deepEqual(v.touched, []);
});

// ---------------------------------------------------------------- the worker's record of a press
function loadWorker(reply) {
  const listeners = [];
  const fetches = [];
  const local = new Map([["api", "http://api.test"]]);
  const session = new Map();
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
    storage: { local: area(local), session: area(session) },
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
  return { send, fetches, local, session };
}

test("the worker: one press on record at a time, kept until the API has its run, given back when never made", async () => {
  let status = 200;
  const w = loadWorker((f) => [status, status < 400 ? (f.url.endsWith("/due") ? due(LIVE) : { at: "x" }) : { detail: "a live run in a league that is not live" }]);
  const key = `start_active_press:${LEAGUE}`;
  const record = { day: DAY, trigger: "routine", reasons: ["week_start"], roster: ROSTER, page: `/nba/${LEAGUE}/${TEAM}` };
  assert.equal((await w.send({ op: "start_active_due" })).data.leagues[0].league, LEAGUE);
  assert.equal(w.fetches[0].url, "http://api.test/autopilot/start-active/due");
  assert.equal((await w.send({ op: "start_active_record", league: LEAGUE })).data, null);
  assert.deepEqual(await w.send({ op: "start_active_pressing", league: LEAGUE, record }), { ok: true, data: { kept: true } });
  assert.deepEqual([w.local.get(key).logged, w.local.get(key).tab, w.local.get(key).prev], [false, 7, null]);
  // While it awaits its log, no other tab presses the league.
  const again = await w.send({ op: "start_active_pressing", league: LEAGUE, record }, 8);
  assert.deepEqual([again.ok, again.error], [false, "a press in this league awaits its log"]);
  // Logged: kept as the day's press; the panel's line set.
  const run = { day: DAY, mode: "live", trigger: "routine", outcome: "started", reason: null, message: UPDATED };
  assert.equal((await w.send({ op: "start_active_log", league: LEAGUE, run, pressed: true })).ok, true);
  assert.equal(w.fetches.at(-1).url, `http://api.test/seasons/${LEAGUE}/autopilot/start-active`);
  assert.deepEqual([w.local.get(key).logged, w.local.get(key).run.message], [true, UPDATED]);
  assert.deepEqual([w.session.get(`start_active:${LEAGUE}`).outcome, w.session.get(`start_active:${LEAGUE}`).message], ["started", UPDATED]);
  // The same day on the same roster is refused; a changed roster is taken, and when that press is
  // never made the day's first press comes back.
  const same = await w.send({ op: "start_active_pressing", league: LEAGUE, record: { ...record, reasons: ["no_run"] } });
  assert.match(same.error, /ran in this league today/);
  const changed = { ...record, reasons: ["no_run"], roster: { players: [2001, 2009], held: [] } };
  assert.equal((await w.send({ op: "start_active_pressing", league: LEAGUE, record: changed })).ok, true);
  assert.equal(w.local.get(key).prev.run.message, UPDATED);
  await w.send({ op: "start_active_log", league: LEAGUE, run: { ...run, outcome: "skipped", reason: "x", message: null }, release: true });
  assert.deepEqual([w.local.get(key).logged, w.local.get(key).roster, w.local.get(key).run.message], [true, ROSTER, UPDATED]);
  // A log that fails keeps the press open with its run; one the API refuses closes it.
  const k2 = `start_active_press:100002`;
  assert.equal((await w.send({ op: "start_active_pressing", league: "100002", record })).ok, true);
  status = 503;
  assert.equal((await w.send({ op: "start_active_log", league: "100002", run, pressed: true })).ok, false);
  assert.deepEqual([w.local.get(k2).logged, w.local.get(k2).run.outcome], [false, "started"]);
  status = 409;
  assert.equal((await w.send({ op: "start_active_log", league: "100002", run, pressed: true })).ok, false);
  assert.deepEqual([w.local.get(k2).logged, w.local.get(k2).refused], [true, "a live run in a league that is not live"]);
  // A dry run's log never touches a record.
  status = 200;
  assert.equal((await w.send({ op: "start_active_log", league: "100003", run: { ...run, mode: "dry_run", outcome: "would_start" } })).ok, true);
  assert.equal(w.local.has("start_active_press:100003"), false);
});
