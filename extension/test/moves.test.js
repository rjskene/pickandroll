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
  assert.deepEqual(p.fields, ["stage", "stat1", "stat2", "apid", "dpid", "faab"]);
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
