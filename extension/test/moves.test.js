// node --test extension/test/*.test.js
// The moves executor (#171): the add page's controls read, a due entry's checks on them, the pass
// the log takes, the strip, the panel's links, the content script on an add page opened with the
// routine's fragment, and the live claim (PR 3): Yahoo's claim step on a fake page (0.8.2), the
// alert recorder, the page Yahoo lands on, and the worker's record of a submit. Nothing here reaches Yahoo. Fixtures carry Yahoo ids,
// slot codes and dollar figures only.
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

/** An add page as the content script extracts it from the rendered page: the anti-forgery field
 * left out, ``token`` saying the form has it. ``markers`` puts an icon on a roster row,
 * ``addClasses`` on the add's own row. */
function rawPage({ token = true, add = ADD, budget = 100, waiver = "Oct 26", heading = X.CLAIM_HEADING, form = true, markers = {}, addClasses = "noactionda- F-icon T-action-icon-disabled-add", action = `/nba/${LEAGUE}/${TEAM}/addplayer`, submit = X.SUBMIT, hint = true, message = null, drops = true } = {}) {
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
            hidden("stat1", "P"),
            hidden("stat2", "P"),
            hidden("apid", String(add)),
            ...(drops ? ROSTER : []).filter((k) => !cut.has(k)).map((k) => ({ name: "dpid", tag: "input", type: "checkbox", value: String(k), checked: false })),
            { name: "faab", tag: "input", type: "text", value: "0", checked: false },
          ],
          token,
        }
      : null,
    submit: form ? submit : null,
    panel: `Your Bid $ Your Budget $${budget}${waiver ? ` Waiver Date ${waiver}` : ""}`,
    hint: hint ? `Must be between $0 and $${budget}` : null,
    add_row: { id: String(add), classes: addClasses },
    rows: (drops ? ROSTER : []).map((k) => ({ id: String(k), classes: CANTCUT.includes(k) ? ICON.cantcut : markers[k] ? ICON[markers[k]] : "" })),
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
  assert.deepEqual([p.submit, p.token, p.heading], [X.SUBMIT, true, X.CLAIM_HEADING]);
  assert.deepEqual(p.fields, ["stage", "stat1", "stat2", "apid", "dpid", "faab"]);
  assert.equal(X.readAddPage(rawPage({ token: false }), CLEARS).token, false);
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
  assert.deepEqual([c.token, c.heading, c.waiver_date, c.budget, c.adds_left, c.read_at], [true, X.CLAIM_HEADING, CLEARS, 100, 4, READ_AT]);
  assert.deepEqual([c.cantcut, c.add_markers, c.bid_range, c.drops], [CANTCUT, ["disabled_add"], [0, 100], 11]);
  // The log says only whether the anti-forgery field is there: nothing spells its name.
  assert.ok(!X.TOKEN.test(JSON.stringify(line)));
  assert.equal(X.moveCheck(e, check, X.readAddPage(rawPage({ token: false }), e.from), due(), READ_AT).controls.token, false);
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
  // An entry with no drop is read on its page (#199); a drop is checked against the protected.
  assert.equal(X.entryProblem(entry({ drop: null }), due()), null);
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
  // A live league whose guard refuses now logs a dry run that says why.
  const refused = due({ mode: "live", live: { ok: false, reason: "a dry run on 7 days first: 3 so far" } });
  run = X.movesPass({ due: refused, trigger: "panel", checks: [line({ outcome: "would_claim" })] });
  assert.deepEqual([run.mode, run.outcome, run.reason], ["dry_run", "would_claim", "live refused: a dry run on 7 days first: 3 so far"]);
  // Where the guard holds, a pass from the add page logs only what it skipped.
  run = X.movesPass({ due: due({ mode: "live", live: { ok: true, reason: null } }), trigger: "routine", checks: [line({ outcome: "skipped", reason: "page not read" })] });
  assert.deepEqual([run.mode, run.outcome, run.reason], ["live", "skipped", "page not read"]);
});

test("the mode a pass runs in: live only where the league is live and its guard holds now", () => {
  assert.deepEqual(X.passMode(due()), { mode: "dry_run", refused: null });
  assert.deepEqual(X.passMode(due({ mode: "live", live: { ok: true, reason: null } })), { mode: "live", refused: null });
  assert.deepEqual(X.passMode(due({ mode: "live", live: { ok: false, reason: "STOP is on (data/autopilot/STOP)" } })), {
    mode: "dry_run",
    refused: "live refused: STOP is on (data/autopilot/STOP)",
  });
  assert.deepEqual(X.passMode(due({ mode: "live" })), { mode: "dry_run", refused: "live refused: the guard did not answer" });
  // Held back in live whatever the page: a free-agent add and an open-spot claim.
  const page = X.readAddPage(rawPage(), CLEARS);
  assert.equal(X.submitProblem(entry(), page), null);
  assert.equal(X.submitProblem(entry({ availability: "FA" }), page), "a free-agent add: this build places waiver claims only");
  assert.equal(X.submitProblem(entry(), X.readAddPage(rawPage({ heading: "Add Player" }), CLEARS)), "a free-agent add: this build places waiver claims only");
  assert.equal(X.submitProblem(entry({ drop: null }), page), "open spot, read only: an open-spot claim is not submitted until Yahoo's open-spot page has been seen");
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
  // In a live league whose guard holds, the panel's link places the claim and says so.
  const live = due({ mode: "live", live: { ok: true, reason: null } });
  assert.equal(X.dueLinks(live)[0].text, "claim: add 3001, drop 2005, $3");
  // An open spot is only read in live (#199): its link places nothing and says no "claim".
  const open = { ...e, drop: null };
  assert.equal(X.dueLinks({ ...live, entries: [open] })[0].text, "add 3001, open spot, $3");
  assert.equal(X.dueLinks({ ...due(), entries: [open] })[0].text, "add 3001, open spot, $3");
  const refused = due({ mode: "live", live: { ok: false, reason: "a dry run on 7 days first: 3 so far" } });
  const dry = X.movesPass({ due: refused, trigger: "routine", checks: [X.moveCheck(e, X.pageCheck(e, page, refused), page, refused, READ_AT)] });
  assert.equal(X.movesStripText({ due: refused, run: dry, at }), "dry run (live refused: a dry run on 7 days first: 3 so far) · would claim for $3, dropping 2005; logged 09:02");
  assert.equal(X.movesStripText({ due: live }), "live · nothing due now");
});

test("only the live claim touches a page: the drop's button, its bid and the final button, nothing fetched", () => {
  const claim = X.fillClaim.toString();
  for (const f of ["lib/moves.js", "league.js", "addpage.js"]) {
    const src = fs.readFileSync(path.join(DIR, f), "utf8").replace(claim, "");
    assert.ok(!/\.click\(|dispatchEvent|submit\(|requestSubmit/.test(src), `${f} clicks or submits outside fillClaim`);
    assert.ok(!/\.(value|selectedIndex|checked)\s*=[^=]/.test(src), `${f} sets a field outside fillClaim`);
    assert.ok(!/\bfetch\(|XMLHttpRequest|DOMParser/.test(src), `${f} fetches a page`);
  }
  assert.equal(claim.match(/\.click\(\)/g).length, 2, "the drop's button and the final button");
  assert.deepEqual(claim.match(/\w+\.(value|checked|selectedIndex)\s*=[^=]/g), ["bid.value = "]);
  assert.ok(!/submit\(|requestSubmit|crumb|TOKEN|fetch\(/.test(claim));
});

// ---------------------------------------------------------------- the live claim on a fake page
/** Yahoo's claim step on a fake add page, as its script reads (2026-10-26). Beside each drop box
 * is a button whose ``data-check-box-value`` names the drop with a trailing space. A click on it
 * ticks the box and posts the form's first stage; the reply lands ``after`` looks later (a look is
 * one ``wait``) and swaps in the final button, shows the submit container and brings its own
 * boxes, the drop's ticked. A click on a box itself only ticks it: no reply, no final button.
 * ``reply``: "swap", "none" (it never comes), "hidden" (the container stays hidden), "unchecked"
 * (the reply's box is not ticked), or an alert's text (Yahoo alerts and swaps nothing).
 * ``finalAlert`` is Yahoo's alert on the final click, ``finalName`` the final button's name,
 * ``balance`` the bid field's (null: none), ``sticky`` a bid that refuses what is typed,
 * ``buttons: false`` a page with no drop buttons, ``dupe`` a second button for that drop, ``rehide``
 * the container hidden again once the bid is typed. Every click, value set and event goes in
 * ``touched``. */
function claimStep({ ticked = [], after = 1, reply = "swap", finalAlert = null, finalName = null, balance = 100, sticky = false, add = ADD, buttons = true, dupe = null, rehide = false } = {}) {
  const touched = [];
  const alerts = [];
  const droppable = ROSTER.filter((k) => !CANTCUT.includes(k));
  const input = (name, type, value) => ({ name, tagName: "INPUT", type, value, checked: false, dispatchEvent: (ev) => touched.push(`event ${ev.type}`) });
  const box = (k, checked) => {
    const b = input("dpid", "checkbox", String(k));
    b.checked = checked;
    b.click = () => {
      touched.push(`click dpid ${k}`);
      b.checked = !b.checked;
    };
    return b;
  };
  let boxes = droppable.map((k) => box(k, ticked.includes(k)));
  let bidValue = "0";
  let hiddenAgain = false;
  const bid = {
    name: "faab",
    tagName: "INPUT",
    type: "text",
    checked: false,
    get value() {
      return bidValue;
    },
    set value(v) {
      touched.push(`set faab ${v}`);
      if (!sticky) bidValue = v;
      if (rehide) hiddenAgain = true;
    },
    getAttribute: (a) => (a === X.BALANCE_ATTR && balance != null ? String(balance) : null),
    dispatchEvent: (ev) => touched.push(`event ${ev.type}`),
  };
  const fixed = [input("stage", "hidden", "2"), input(X.TOKEN_FIELD, "hidden", "SECRET-VALUE"), input("stat1", "hidden", "P"), input("stat2", "hidden", "P"), input("apid", "hidden", String(add))];
  let swapped = false;
  let pending = null;
  const land = () => {
    pending = null;
    if (reply === "none") return;
    if (!["swap", "hidden", "unchecked"].includes(reply)) {
      alerts.push(reply);
      return;
    }
    const drop = boxes.find((b) => b.checked);
    boxes = droppable.map((k) => box(k, reply !== "unchecked" && Boolean(drop) && drop.value === String(k)));
    swapped = true;
  };
  const trigger = (k) => ({
    getAttribute: (a) => (a === X.DROP_TRIGGER_VALUE ? `${k} ` : null),
    click: () => {
      touched.push(`click drop button ${k}`);
      const b = boxes.find((x) => x.value === String(k));
      if (b) b.checked = true;
      pending = after;
      if (pending <= 0) land();
    },
  });
  const triggers = buttons ? [...droppable, ...(dupe != null ? [dupe] : [])].map(trigger) : [];
  const final = {
    getAttribute: (a) => (a === "name" ? finalName : null),
    click: () => {
      touched.push("click final");
      if (finalAlert) alerts.push(finalAlert);
    },
  };
  const container = {
    get className() {
      return swapped && reply !== "hidden" && !hiddenAgain ? "Inline" : `Inline ${X.SUBMIT_HIDDEN}`;
    },
    querySelector: (sel) => (sel === X.FINAL_BUTTON && swapped ? final : null),
    textContent: ` <input type="submit" id="submit-add-drop-button" name="${X.SUBMIT}" value="Create claim"> `,
  };
  const form = {
    get elements() {
      return [...fixed, ...boxes, bid];
    },
    querySelectorAll: (sel) => (sel === X.DROP_TRIGGER ? triggers : []),
  };
  const wait = async () => {
    if (pending != null && --pending <= 0) land();
  };
  const root = { getAttribute: (a) => (a === X.ALERTS_ATTR && alerts.length ? JSON.stringify(alerts) : null) };
  return { form, container, root, wait, touched, boxes: () => boxes };
}

/** ``claimStep``'s page as ``fillClaim`` reads it. */
function claimDoc(opts = {}) {
  const step = claimStep(opts);
  const doc = {
    querySelector: (sel) => (sel === `form#${X.FORM_ID}` ? step.form : null),
    getElementById: (id) => (id === X.SUBMIT_CONTAINER ? step.container : null),
    documentElement: step.root,
  };
  return { ...step, doc };
}

test("Yahoo's page: a click on the drop box brings no claim step, its button does (0.8.1's miss)", async () => {
  // 0.8.1 clicked the box and waited for the submit: the page never answers that.
  let v = claimDoc();
  v.boxes().find((b) => b.value === "2005").click();
  for (let i = 0; i < 100; i++) await v.wait();
  assert.deepEqual([v.container.querySelector(X.FINAL_BUTTON), v.container.className], [null, `Inline ${X.SUBMIT_HIDDEN}`]);
  // The button: Yahoo's reply brings the final button, shows the container and ticks the drop.
  v = claimDoc();
  v.form.querySelectorAll(X.DROP_TRIGGER)[4].click();
  await v.wait();
  assert.ok(v.container.querySelector(X.FINAL_BUTTON));
  assert.equal(v.container.className, "Inline");
  assert.deepEqual(v.boxes().filter((b) => b.checked).map((b) => b.value), ["2005"]);
});

test("the live claim clicks the drop's button, waits for Yahoo's reply, types the bid and clicks the final button once", async () => {
  const v = claimDoc({ after: 3 });
  assert.equal(await X.fillClaim(v.doc, entry(), { wait: v.wait }), null);
  // Never the box, the bid only once the reply is in, and nothing else.
  assert.deepEqual(v.touched, ["click drop button 2005", "set faab 3", "event input", "event change", "click final"]);
  // A struck bid is a $0 claim; a final button named as the noscript's is the claim's.
  const zero = claimDoc({ finalName: X.SUBMIT });
  assert.equal(await X.fillClaim(zero.doc, entry({ bid_placed: 0 }), { wait: zero.wait }), null);
  assert.ok(zero.touched.includes("set faab 0") && zero.touched.includes("click final"));
});

test("the live claim touches nothing before its button: no single box or button, a box ticked, no form", async () => {
  const run = async (opts, e = entry()) => {
    const v = claimDoc(opts);
    return [await X.fillClaim(v.doc, e, { wait: v.wait }), v.touched];
  };
  const skip = (reason) => ({ outcome: "skipped", reason });
  assert.deepEqual(await run({}, entry({ drop: 2012 })), [skip("no single drop box for 2012"), []]);
  assert.deepEqual(await run({ ticked: [2001] }), [skip("a drop box was ticked before the pass"), []]);
  assert.deepEqual(await run({ buttons: false }), [skip("no single drop button for 2005 (0 on the page)"), []]);
  assert.deepEqual(await run({ dupe: 2005 }), [skip("no single drop button for 2005 (2 on the page)"), []]);
  assert.deepEqual(await X.fillClaim({ querySelector: () => null }, entry(), { wait: async () => {} }), skip("the claim form is gone"));
});

test("Yahoo's reply that never comes, or comes short, is a skip naming the signs missing; the page is left as it is", async () => {
  const run = async (opts) => {
    const v = claimDoc(opts);
    let looks = 0;
    const wait = async () => {
      looks += 1;
      await v.wait();
    };
    return [await X.fillClaim(v.doc, entry(), { wait, every: 200, cap: 1000 }), v.touched, looks];
  };
  const late = "Yahoo's claim step did not come back within 1 s: ";
  assert.deepEqual(await run({ reply: "none" }), [{ outcome: "skipped", reason: `${late}the final button is not there; the submit is still hidden` }, ["click drop button 2005"], 5]);
  assert.deepEqual(await run({ reply: "hidden" }), [{ outcome: "skipped", reason: `${late}the submit is still hidden` }, ["click drop button 2005"], 5]);
  assert.deepEqual(await run({ reply: "unchecked" }), [{ outcome: "skipped", reason: `${late}the drop box is not checked` }, ["click drop button 2005"], 5]);
  // Too slow: the reply landing after the cap is never acted on.
  assert.deepEqual((await run({ after: 6 }))[0].reason, `${late}the final button is not there; the submit is still hidden`);
  assert.equal(X.SWAP_MS, 15000);
});

test("Yahoo's alerts: the tick's is a failure in Yahoo's words, the final click's a skip; no final click after one", async () => {
  let v = claimDoc({ reply: "This player cannot be dropped." });
  assert.deepEqual(await X.fillClaim(v.doc, entry(), { wait: v.wait }), { outcome: "failed", reason: 'Yahoo answered the drop\'s tick: "This player cannot be dropped."' });
  assert.deepEqual(v.touched, ["click drop button 2005"]);
  v = claimDoc({ finalAlert: "FAAB bid must be a whole number betweed $0 and $100" });
  assert.deepEqual(await X.fillClaim(v.doc, entry(), { wait: v.wait }), { outcome: "skipped", reason: 'Yahoo refused the final click: "FAAB bid must be a whole number betweed $0 and $100"' });
  assert.equal(v.touched.filter((t) => t === "click final").length, 1);
  // Alerts kept before the pass are not this claim's.
  v = claimDoc();
  const kept = v.doc.documentElement;
  v.doc.documentElement = { getAttribute: (a) => (a === X.ALERTS_ATTR ? JSON.stringify(["an earlier alert"]) : kept.getAttribute(a)) };
  assert.equal(await X.fillClaim(v.doc, entry(), { wait: v.wait }), null);
  assert.deepEqual(X.alertsOf({ documentElement: { getAttribute: () => "not json" } }), []);
  assert.deepEqual(X.alertsOf({}), []);
});

test("the bid is checked as Yahoo checks it, after the reply, and read back before the final click", async () => {
  const run = async (opts, e = entry()) => {
    const v = claimDoc(opts);
    return [await X.fillClaim(v.doc, e, { wait: v.wait }), v.touched];
  };
  const tick = "click drop button 2005";
  assert.deepEqual(await run({ balance: 2 }), [{ outcome: "skipped", reason: "the bid ($3) is outside Yahoo's $0 to $2" }, [tick]]);
  assert.deepEqual(await run({ balance: null }), [{ outcome: "skipped", reason: "the bid field shows no balance" }, [tick]]);
  assert.deepEqual(await run({}, entry({ bid_placed: 2.5 })), [{ outcome: "skipped", reason: "the bid ($2.5) is outside Yahoo's $0 to $100" }, [tick]]);
  assert.equal(X.bidProblem({ getAttribute: () => "3" }, 3), null);
  // The form read back wrong: no final click.
  let [got, touched] = await run({ sticky: true });
  assert.deepEqual([got.reason, touched.includes("click final")], ["the form did not take the claim: its bid reads 0", false]);
  [got, touched] = await run({ add: 3002 });
  assert.deepEqual([got.reason, touched.includes("click final")], ["the form did not take the claim: its apid is not the add", false]);
  [got, touched] = await run({ finalName: "submit_something_else" });
  assert.deepEqual([got.reason, touched.includes("click final")], ["the form did not take the claim: its final button is not the claim's", false]);
  [got, touched] = await run({ rehide: true });
  assert.deepEqual([got.reason, touched.includes("click final")], ["the form did not take the claim: its final button is not the claim's", false]);
});

test("the alert recorder: only on an add page opened with a moves fragment", () => {
  const R = require("../addpage.js");
  assert.deepEqual([...R.FRAGMENTS].sort(), Object.keys(X.MOVES_TRIGGERS).sort());
  assert.equal(R.ATTR, X.ALERTS_ATTR);
  const page = (pathname, hash) => {
    const attrs = {};
    const shown = [];
    const win = {
      location: { pathname, hash },
      alert: (m) => shown.push(m),
      document: { documentElement: { getAttribute: (a) => attrs[a] ?? null, setAttribute: (a, v) => (attrs[a] = v) } },
    };
    return { win, shown, installed: R.install(win) };
  };
  const p = page(`/nba/${LEAGUE}/addplayer`, "#pickandroll-moves");
  assert.equal(p.installed, true);
  p.win.alert("This player cannot be dropped.");
  p.win.alert("x".repeat(400));
  assert.deepEqual(p.shown, []);
  const got = X.alertsOf(p.win.document);
  assert.deepEqual([got[0], got[1].length], ["This player cannot be dropped.", 300]);
  // A page opened by hand, or another page of the league, keeps Yahoo's alerts.
  for (const [where, hash] of [[`/nba/${LEAGUE}/addplayer`, ""], [`/nba/${LEAGUE}/addplayer`, "#other"], [`/nba/${LEAGUE}/${TEAM}`, "#pickandroll-moves"]]) {
    const q = page(where, hash);
    q.win.alert("shown");
    assert.deepEqual([q.installed, q.shown], [false, ["shown"]]);
  }
  for (const hash of ["#pickandroll-moves-late", "#pickandroll-moves-panel"]) assert.equal(page(`/nba/${LEAGUE}/addplayer`, hash).installed, true);
});

test("the page Yahoo lands on: placed, refused or not recognised", () => {
  const read = (over) => X.readLanded({ path: `/nba/${LEAGUE}/${TEAM}`, heading: null, form: false, notes: [], errors: [], pending: false, ...over });
  assert.deepEqual(read({ notes: ["Your waiver claim has been submitted."] }), { outcome: "claimed", message: "Your waiver claim has been submitted." });
  assert.deepEqual(read({ pending: true }), { outcome: "claimed", message: "the add shows among the pending claims" });
  assert.deepEqual(read({ errors: ["You have exceeded the maximum number of adds."] }), { outcome: "failed", message: "You have exceeded the maximum number of adds." });
  assert.deepEqual(read({ form: true, notes: ["Bid must be a whole number."] }), { outcome: "failed", message: "Bid must be a whole number." });
  // The claim form back with nothing said, a confirm step, any other page: not recognised.
  assert.equal(read({ form: true }), null);
  assert.equal(read({ heading: "Confirm Transaction" }), null);
  assert.equal(read({ form: true, pending: true }), null);
});

test("a submitted claim's live pass: Yahoo's answer, or its answer not read", () => {
  const e = entry();
  const page = X.readAddPage(rawPage(), e.from);
  const live = due({ mode: "live", live: { ok: true, reason: null } });
  const line = X.moveCheck(e, { outcome: "would_claim", reason: null }, page, live, READ_AT);
  const at = new Date(2026, 9, 24, 9, 2).getTime();
  const record = { day: DAY, trigger: "routine", line, league: LEAGUE, tab: 7, at };
  const seen = { path: `/nba/${LEAGUE}/${TEAM}`, heading: null };
  let run = X.landedPass(record, { outcome: "claimed", message: "claim submitted" }, seen, "0.8.0");
  assert.deepEqual([run.day, run.mode, run.trigger, run.outcome, run.reason, run.extension], [DAY, "live", "routine", "claimed", null, "0.8.0"]);
  const got = run.entries[0];
  assert.deepEqual([got.id, got.outcome, got.reason, got.message, got.bid, got.drop], [e.id, "claimed", null, "claim submitted", 3, 2005]);
  // The fields it filled and the page it landed on; never the anti-forgery field.
  assert.deepEqual(got.controls.would_fill, { action: `/nba/${LEAGUE}/${TEAM}/addplayer`, apid: ADD, dpid: 2005, faab: 3, submit: X.SUBMIT });
  assert.deepEqual(got.controls.landed, seen);
  assert.ok(!X.TOKEN.test(JSON.stringify(run)));
  run = X.landedPass(record, { outcome: "failed", message: "Too many adds." }, seen);
  assert.deepEqual([run.outcome, run.reason, run.entries[0].reason, run.entries[0].message], ["failed", "Too many adds.", "Too many adds.", "Too many adds."]);
  // Not recognised or never read: claimed, so it counts and is never submitted again.
  run = X.landedPass(record, null, null);
  assert.deepEqual([run.outcome, run.entries[0].outcome, run.entries[0].reason], ["claimed", "claimed", "submitted 09:02; Yahoo's answer was not read: check the pending claims"]);
  assert.match(X.landedStripText(X.landedPass(record, { outcome: "claimed", message: "claim submitted" }, seen), at), /^live · claimed for \$3, dropping 2005: Yahoo: claim submitted; logged 09:02$/);
  assert.equal(X.leagueOfPage(`${SITE}/nba/${LEAGUE}/${TEAM}/addplayer`), LEAGUE);
  assert.equal(X.leagueOfPage(`${SITE}/draftclient/${LEAGUE}`), null);
});

// ---------------------------------------------------------------- the content script on an add page
/** A fake element: its text, attributes and children by selector. */
const el = (props = {}) => ({ textContent: "", className: "", getAttribute: (a) => (props.attrs || {})[a] ?? null, querySelectorAll: () => [], querySelector: () => null, closest: () => null, ...props });

/** The rendered add page as the content script sees it: the form with Yahoo's claim step
 * (``claimStep``, its reply landing on the drop button's click; ``step`` passes options to it), the
 * noscript's submit as text, the add's row and my roster's rows with their player ids and icons. */
function addDom({ add = ADD, budget = 100, waiver = "Oct 26", step: opts = {} } = {}) {
  const step = claimStep({ add, balance: budget, after: 0, ...opts });
  const hint = el({ textContent: ` Must be between $0 and $${budget} ` });
  const form = el({ attrs: { action: `${SITE}/nba/${LEAGUE}/${TEAM}/addplayer`, method: "post" }, querySelectorAll: (sel) => (sel === "p, span, div" ? [hint] : step.form.querySelectorAll(sel)) });
  Object.defineProperty(form, "elements", { get: () => step.form.elements, configurable: true });
  const tr = (id, classes) =>
    el({
      querySelector: (sel) => (sel === "[data-ys-playerid]" ? el({ attrs: { "data-ys-playerid": String(id) } }) : null),
      querySelectorAll: (sel) => (sel === '[class*="T-action-icon-"]' && classes ? [el({ className: classes })] : []),
    });
  const addTr = tr(add, "noactionda- F-icon T-action-icon-disabled-add");
  const addCell = el({ attrs: { "data-ys-playerid": String(add) }, closest: (sel) => (sel === "tr" ? addTr : null) });
  const rows = ROSTER.map((k) => tr(k, CANTCUT.includes(k) ? ICON.cantcut : ""));
  return {
    touched: step.touched,
    documentElement: step.root,
    querySelector: (sel) => (sel === "form#add-drop-players-form" ? form : sel === "table#statTable-add tbody tr [data-ys-playerid]" ? addCell : null),
    querySelectorAll: (sel) =>
      sel === "h1, h2, h3"
        ? [el({ textContent: "Yahoo Sports Fantasy Basketball" }), el({ textContent: ` ${X.CLAIM_HEADING} ` })]
        : sel === "table.statTable-drop tbody tr"
          ? rows
          : [],
    getElementById: (id) =>
      id === "faab-bid-fieldset" ? el({ textContent: `Your Bid $ Your Budget $${budget} Waiver Date ${waiver}` }) : id === X.SUBMIT_CONTAINER ? step.container : null,
  };
}

/** league.js on the add page of ``add`` (``hash`` its fragment), a chrome whose worker answers
 * each op with ``answer``. Returns the messages sent, the URLs replaced, the strip and what was
 * touched on the page. ``dom`` and ``url`` put it on another page of the league. */
async function visitAdd({ hash = "#pickandroll-moves", answer, add = ADD, dom = addDom({ add }), url: at = `${SITE}/nba/${LEAGUE}/addplayer?apid=${add}${hash}` }) {
  const nodes = {};
  const doc = {
    ...dom,
    getElementById: (id) => nodes[id] || dom.getElementById(id),
    createElement: () => ({ style: {}, setAttribute() {}, textContent: "" }),
    documentElement: {
      append: (e) => {
        nodes[e.id] = e;
      },
      getAttribute: (a) => (dom.documentElement ? dom.documentElement.getAttribute(a) : null),
    },
  };
  const url = new URL(at);
  const location = { href: url.href, hash: url.hash, pathname: url.pathname, search: url.search, assign() {} };
  const sent = [];
  const replaced = [];
  const timers = [];
  const chrome = {
    runtime: {
      connect: () => ({}),
      getManifest: () => ({ version: "0.8.0" }),
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
    Event,
    console,
  });
  ctx.window = ctx;
  ctx.globalThis = ctx;
  for (const file of ["lib/league.js", "lib/lineup.js", "lib/moves.js", "league.js"]) vm.runInContext(fs.readFileSync(path.join(DIR, file), "utf8"), ctx);
  for (const fn of timers.splice(0)) await fn();
  return { sent, replaced, strip: nodes["pickandroll-strip"], touched: dom.touched || [] };
}

/** The worker's answers: the settings, the due entries, the log taking the pass and the submit
 * records (``records`` on file, ``landing`` this tab's claim awaiting its answer, ``kept`` whether
 * a new one is put on record). */
const worker =
  (over = {}, settings = {}, { records = [], landing = null, kept = true } = {}) =>
  (msg) => {
    if (msg.op === "settings") return { ok: true, data: { lineup_executor: "on", moves_executor: "on", ...settings } };
    if (msg.op === "moves_due") return { ok: true, data: due(over) };
    if (msg.op === "moves_log") return { ok: true, data: { at: "x" } };
    if (msg.op === "moves_landed") return { ok: true, data: landing };
    if (msg.op === "moves_submits") return { ok: true, data: records };
    if (msg.op === "moves_submitting") return kept ? { ok: true, data: { kept: true } } : { ok: false, error: "this claim was submitted already" };
    return { ok: false, error: `unexpected ${msg.op}` };
  };
const ops = (v) => v.sent.map((m) => m.op);
const sentOf = (v, op) => v.sent.filter((m) => m.op === op);
const PASS = ["moves_landed", "settings", "moves_submits", "moves_due"];

test("the routine's link: the fragment dropped, the page's entry checked on the rendered form and the claim it would place logged", async () => {
  const v = await visitAdd({ answer: worker({ entries: [entry({ id: "other", add: 3002, page: `/nba/${LEAGUE}/addplayer?apid=3002` }), entry()] }) });
  assert.deepEqual(v.replaced, [`/nba/${LEAGUE}/addplayer?apid=${ADD}`]);
  // Nothing is posted for the add page: a claim awaiting its answer, the submits on record, the
  // due entries, then the pass. A dry run touches nothing.
  assert.deepEqual(ops(v), [...PASS, "moves_log"]);
  assert.equal(sentOf(v, "moves_due")[0].league, LEAGUE);
  assert.deepEqual(v.touched, []);
  const run = sentOf(v, "moves_log")[0].run;
  assert.deepEqual([run.mode, run.trigger, run.outcome, run.extension], ["dry_run", "routine", "would_claim", "0.8.0"]);
  assert.deepEqual(run.entries.map((e) => [e.id, e.outcome]), [[entry().id, "would_claim"]]);
  const c = run.entries[0].controls;
  assert.deepEqual(c.would_fill, { action: `/nba/${LEAGUE}/${TEAM}/addplayer`, apid: ADD, dpid: 2005, faab: 3, submit: X.SUBMIT });
  assert.deepEqual([c.token, c.cantcut, c.add_markers, c.fields], [true, CANTCUT, ["disabled_add"], ["stage", "stat1", "stat2"]]);
  const sent = JSON.stringify(v.sent);
  assert.ok(!sent.includes("SECRET-VALUE") && !X.TOKEN.test(sent), "the anti-forgery field's value and name never leave the page");
  assert.match(v.strip.textContent, /^pickandroll moves: dry run · would claim for \$3, dropping 2005; logged \d\d:\d\d$/);
});

test("the late pass and the panel's link carry their triggers", async () => {
  let v = await visitAdd({ hash: "#pickandroll-moves-late", answer: worker() });
  assert.equal(sentOf(v, "moves_log")[0].run.trigger, "routine_late");
  v = await visitAdd({ hash: "#pickandroll-moves-panel", answer: worker() });
  assert.equal(sentOf(v, "moves_log")[0].run.trigger, "panel");
});

test("a plain visit runs nothing; a player not due logs nothing", async () => {
  // A plain visit only asks whether this tab submitted a claim awaiting its answer.
  let v = await visitAdd({ hash: "", answer: worker() });
  assert.deepEqual([ops(v), v.replaced], [["moves_landed"], []]);
  v = await visitAdd({ answer: worker({ entries: [] }) });
  assert.deepEqual(ops(v), PASS);
  assert.equal(v.strip.textContent, "pickandroll moves: dry run · this player is not due in the queue: nothing logged");
});

test("off in the league, the browser's brake and STOP", async () => {
  let v = await visitAdd({ answer: worker({ mode: "off", entries: [] }) });
  assert.ok(!ops(v).includes("moves_log"));
  assert.equal(v.strip.textContent, "pickandroll moves: off in this league");
  v = await visitAdd({ answer: worker({}, { moves_executor: "off" }) });
  assert.deepEqual(ops(v), ["moves_landed", "settings"]);
  assert.equal(v.strip.textContent, "pickandroll moves: off in this browser (the extension's settings)");
  v = await visitAdd({ answer: worker({ stop: true, entries: [] }) });
  const run = sentOf(v, "moves_log")[0].run;
  assert.deepEqual([run.outcome, run.entries], ["stopped", []]);
});

test("a check that fails before the page still logs what the page showed", async () => {
  const v = await visitAdd({ answer: worker({ protected: { 2005: "kept: returns" } }) });
  const e = sentOf(v, "moves_log")[0].run.entries[0];
  assert.deepEqual([e.outcome, e.reason], ["skipped", "the drop is protected (kept: returns)"]);
  assert.equal(e.controls.would_fill, null);
  assert.equal(e.controls.heading, X.CLAIM_HEADING);
});

// ---------------------------------------------------------------- the live claim from the content script
const LIVE = { mode: "live", live: { ok: true, reason: null } };

test("in a live league whose guard holds, the claim is put on record, then placed on the page; its pass waits for the answer", async () => {
  const v = await visitAdd({ answer: worker(LIVE) });
  assert.deepEqual(ops(v), [...PASS, "moves_submitting"]);
  assert.deepEqual(v.touched, ["click drop button 2005", "set faab 3", "event input", "event change", "click final"]);
  const { record, league } = sentOf(v, "moves_submitting")[0];
  assert.equal(league, LEAGUE);
  assert.deepEqual([record.day, record.trigger, record.line.id, record.line.outcome, record.line.bid], [DAY, "routine", entry().id, "would_claim", 3]);
  assert.deepEqual(record.line.controls.would_fill, { action: `/nba/${LEAGUE}/${TEAM}/addplayer`, apid: ADD, dpid: 2005, faab: 3, submit: X.SUBMIT });
  assert.ok(!JSON.stringify(v.sent).includes("SECRET-VALUE") && !X.TOKEN.test(JSON.stringify(v.sent)));
  assert.equal(v.strip.textContent, "pickandroll moves: live · claim submitted for $3, dropping 2005: reading Yahoo's answer…");
});

test("in a live league Yahoo's alert on the drop's tick is the entry's failure, in Yahoo's words: no bid, no final click", async () => {
  const v = await visitAdd({ answer: worker(LIVE), dom: addDom({ step: { reply: "This player cannot be dropped." } }) });
  assert.deepEqual(ops(v), [...PASS, "moves_submitting", "moves_log"]);
  assert.deepEqual(v.touched, ["click drop button 2005"]);
  const run = sentOf(v, "moves_log")[0].run;
  assert.deepEqual([run.mode, run.outcome, run.entries[0].outcome], ["live", "failed", "failed"]);
  assert.equal(run.entries[0].reason, 'Yahoo answered the drop\'s tick: "This player cannot be dropped."');
  assert.match(v.strip.textContent, /^pickandroll moves: live · failed: Yahoo answered the drop's tick: "This player cannot be dropped\." \(\d\d:\d\d\)$/);
});

test("a live league with the guard refusing, a failed check, a free-agent add or no record: nothing is touched", async () => {
  // The guard refusing now: a dry run that says why.
  let v = await visitAdd({ answer: worker({ mode: "live", live: { ok: false, reason: "a dry run on 7 days first: 3 so far" } }) });
  let run = sentOf(v, "moves_log")[0].run;
  assert.deepEqual([run.mode, run.outcome, run.reason, v.touched], ["dry_run", "would_claim", "live refused: a dry run on 7 days first: 3 so far", []]);
  // A check that fails: a live skip, which stays due for the late pass.
  v = await visitAdd({ answer: worker({ ...LIVE, protected: { 2005: "kept: returns" } }) });
  run = sentOf(v, "moves_log")[0].run;
  assert.deepEqual([run.mode, run.outcome, run.entries[0].reason, v.touched, sentOf(v, "moves_submitting")], ["live", "skipped", "the drop is protected (kept: returns)", [], []]);
  // A free-agent add is held back in live.
  v = await visitAdd({ answer: worker({ ...LIVE, entries: [entry({ availability: "FA" })] }) });
  run = sentOf(v, "moves_log")[0].run;
  assert.deepEqual([run.outcome, run.entries[0].reason, v.touched], ["skipped", "a free-agent add: this build places waiver claims only", []]);
  // The worker refuses to put the submit on record: nothing is touched.
  v = await visitAdd({ answer: worker(LIVE, {}, { kept: false }) });
  run = sentOf(v, "moves_log")[0].run;
  assert.deepEqual([run.outcome, run.entries[0].reason, v.touched], ["skipped", "the submit could not be put on record", []]);
  // A plain visit to the add page of a live league submits nothing.
  v = await visitAdd({ hash: "", answer: worker(LIVE) });
  assert.deepEqual([ops(v), v.touched], [["moves_landed"], []]);
});

test("a submit on record is never made again: a stale one is logged first with its answer not read", async () => {
  const line = { id: entry().id, add: ADD, drop: 2005, bid: 3, outcome: "would_claim", reason: null, page: entry().page, controls: { would_fill: { dpid: 2005 } }, message: null };
  const fresh = { day: DAY, trigger: "routine", line, league: LEAGUE, tab: 9, at: Date.now() };
  let v = await visitAdd({ answer: worker(LIVE, {}, { records: [fresh] }) });
  assert.deepEqual([ops(v), v.touched], [PASS, []]);
  assert.equal(v.strip.textContent, "pickandroll moves: live · a submit of this claim awaits Yahoo's answer: nothing done");
  const stale = { ...fresh, at: Date.now() - X.LANDING_MS - 1000 };
  v = await visitAdd({ answer: worker(LIVE, {}, { records: [stale] }) });
  const [first] = sentOf(v, "moves_log");
  assert.deepEqual(ops(v).slice(0, 4), ["moves_landed", "settings", "moves_submits", "moves_log"]);
  assert.deepEqual([first.run.mode, first.run.outcome, first.run.entries[0].outcome], ["live", "claimed", "claimed"]);
  assert.match(first.run.entries[0].reason, /^submitted \d\d:\d\d; Yahoo's answer was not read: check the pending claims$/);
  assert.deepEqual(v.touched, []);
});

/** The page Yahoo lands on after a submit: any page of the league, here the claim form's own
 * address. ``notes`` and ``errors`` are its messages, ``form`` whether the claim form is back. */
function landedDom({ notes = [], errors = [], form = false, heading = "Team page" } = {}) {
  const text = (t) => el({ textContent: t });
  return {
    querySelector: (sel) => (sel === `form#${X.FORM_ID}` && form ? el() : null),
    querySelectorAll: (sel) =>
      sel === "h1, h2, h3"
        ? [text("Yahoo Sports Fantasy Basketball"), text(heading)]
        : sel.startsWith(".error")
          ? errors.map(text)
          : sel.startsWith(".Alert")
            ? [...notes, ...errors].map(text)
            : [],
    getElementById: () => null,
    body: text([...notes, ...errors].join(" ")),
  };
}

test("the page Yahoo lands on logs the claim's live pass: placed, refused, or its answer not read", async () => {
  const line = X.moveCheck(entry(), { outcome: "would_claim", reason: null }, X.readAddPage(rawPage(), CLEARS), due(LIVE), READ_AT);
  const landing = { day: DAY, trigger: "routine_late", line, league: LEAGUE, tab: 9, at: Date.now() };
  const landedAt = (dom) => visitAdd({ answer: worker(LIVE, {}, { landing }), dom, url: `${SITE}/nba/${LEAGUE}/${TEAM}/addplayer` });
  let v = await landedAt(landedDom({ notes: ["Your waiver claim has been submitted."] }));
  assert.deepEqual(ops(v), ["moves_landed", "moves_log"]);
  let run = sentOf(v, "moves_log")[0].run;
  assert.deepEqual([run.day, run.mode, run.trigger, run.outcome], [DAY, "live", "routine_late", "claimed"]);
  assert.deepEqual([run.entries[0].message, run.entries[0].controls.landed], ["Your waiver claim has been submitted.", { path: `/nba/${LEAGUE}/${TEAM}/addplayer`, heading: "Team page" }]);
  assert.match(v.strip.textContent, /^pickandroll moves: live · claimed for \$3, dropping 2005: Yahoo: Your waiver claim has been submitted\.; logged \d\d:\d\d$/);
  v = await landedAt(landedDom({ form: true, errors: ["You have reached the maximum number of adds."] }));
  run = sentOf(v, "moves_log")[0].run;
  assert.deepEqual([run.outcome, run.entries[0].reason], ["failed", "You have reached the maximum number of adds."]);
  v = await landedAt(landedDom({ heading: "Confirm Transaction" }));
  run = sentOf(v, "moves_log")[0].run;
  assert.deepEqual([run.outcome, run.entries[0].outcome], ["claimed", "claimed"]);
  assert.match(run.entries[0].reason, /Yahoo's answer was not read/);
  // No claim awaiting its answer in this tab: the page logs nothing.
  v = await visitAdd({ answer: worker(LIVE), dom: landedDom(), url: `${SITE}/nba/${LEAGUE}/${TEAM}/addplayer` });
  assert.deepEqual(ops(v), ["moves_landed"]);
});

// ---------------------------------------------------------------- the worker's record of a submit
/** worker.js with its storage in memory, a fetch answering ``reply(f)`` with [status, data], and
 * messages sent from tab ``tab``. */
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
  return { send, fetches, local };
}

test("the worker keeps a submit on record until the API has its live pass, and never takes it twice", async () => {
  let status = 409;
  const w = loadWorker(() => [status, status < 400 ? { at: "x" } : { detail: "STOP is on: a pass can only say it stopped" }]);
  const line = { id: entry().id, add: ADD, drop: 2005, bid: 3, outcome: "would_claim" };
  const record = { day: DAY, trigger: "routine", line };
  assert.deepEqual(await w.send({ op: "moves_submitting", league: LEAGUE, record }), { ok: true, data: { kept: true } });
  const kept = w.local.get(`moves_submit:${entry().id}`);
  assert.deepEqual([kept.league, kept.tab, kept.day, kept.line.id], [LEAGUE, 7, DAY, entry().id]);
  // A second submit of the entry is refused, whatever the tab.
  const again = await w.send({ op: "moves_submitting", league: LEAGUE, record }, 8);
  assert.deepEqual([again.ok, again.error], [false, "this claim was submitted already"]);
  // The landed page in the same tab finds it; another tab or league does not.
  assert.equal((await w.send({ op: "moves_landed", league: LEAGUE })).data.line.id, entry().id);
  assert.equal((await w.send({ op: "moves_landed", league: LEAGUE }, 8)).data, null);
  assert.equal((await w.send({ op: "moves_landed", league: "100009" })).data, null);
  assert.equal((await w.send({ op: "moves_submits", league: LEAGUE })).data.length, 1);
  // Past the landing window it is no longer this page's, but stays on record for the next pass.
  w.local.set(`moves_submit:${entry().id}`, { ...kept, at: Date.now() - X.LANDING_MS - 1 });
  assert.equal((await w.send({ op: "moves_landed", league: LEAGUE })).data, null);
  assert.equal((await w.send({ op: "moves_submits", league: LEAGUE })).data.length, 1);
  // The API refusing the pass keeps the record; taking it drops it. A dry run drops nothing.
  const run = { day: DAY, mode: "live", trigger: "routine", outcome: "claimed", entries: [{ ...line, outcome: "claimed" }] };
  assert.equal((await w.send({ op: "moves_log", league: LEAGUE, run })).ok, false);
  assert.ok(w.local.has(`moves_submit:${entry().id}`));
  status = 200;
  assert.equal((await w.send({ op: "moves_log", league: LEAGUE, run: { ...run, mode: "dry_run", outcome: "would_claim" } })).ok, true);
  assert.ok(w.local.has(`moves_submit:${entry().id}`));
  assert.equal((await w.send({ op: "moves_log", league: LEAGUE, run })).ok, true);
  assert.equal(w.local.has(`moves_submit:${entry().id}`), false);
  assert.deepEqual((await w.send({ op: "moves_submits", league: LEAGUE })).data, []);
});

test("claims in flight count as placed: against the cap, as pending and against their week's adds", () => {
  const flying = (id, add, over = {}) => ({ day: DAY, trigger: "routine", league: LEAGUE, tab: 9, at: Date.now(), line: { id, add, drop: 2007, controls: { waiver_date: CLEARS } }, ...over });
  const d = due({ ...LIVE, cap: 1 });
  assert.equal(X.withInflight(d, []), d);
  const got = X.withInflight(d, [flying("a", 3009), flying("old", 3010, { day: "2026-10-23" })]);
  assert.equal(got.done, 1);
  assert.deepEqual(got.pending, [{ id: "a", add: 3009, drop: 2007, from: CLEARS }]);
  assert.deepEqual(got.adds_left, [{ start: "2026-10-20", end: "2026-10-26", adds: 3 }]);
  assert.equal(X.entryProblem(entry(), got), "over the day's cap");
  assert.equal(X.entryProblem(entry(), X.withInflight(due(LIVE), [flying("b", ADD)])), "a claim on the add is pending");
  // A claim the API already counts is not counted twice.
  const counted = due({ ...LIVE, done: 1, pending: [{ id: "a", add: 3009, drop: 2007, from: CLEARS }] });
  assert.equal(X.withInflight(counted, [flying("a", 3009)]), counted);
});

test("the worker puts submits on record one at a time, never past the cap or twice on one add", async () => {
  const w = loadWorker(() => [200, { at: "x" }]);
  const record = (id, add) => ({ day: DAY, trigger: "routine", line: { id, add, drop: 2005, outcome: "would_claim" }, cap: 1, done: 0 });
  const [one, two] = await Promise.all([
    w.send({ op: "moves_submitting", league: LEAGUE, record: record("e1", 3001) }, 7),
    w.send({ op: "moves_submitting", league: LEAGUE, record: record("e2", 3002) }, 8),
  ]);
  assert.deepEqual([one.ok, two.ok, two.error], [true, false, "over the day's cap with claims in flight"]);
  const more = (r) => ({ ...r, cap: 3 });
  const same = await w.send({ op: "moves_submitting", league: LEAGUE, record: more(record("e3", 3001)) }, 8);
  assert.deepEqual([same.ok, same.error], [false, "a claim on this add is in flight"]);
  assert.equal((await w.send({ op: "moves_submitting", league: LEAGUE, record: more(record("e4", 3004)) }, 8)).ok, true);
  // Another league's or another day's claims are not this one's.
  assert.equal((await w.send({ op: "moves_submitting", league: "100009", record: record("e5", 3001) }, 8)).ok, true);
  assert.equal((await w.send({ op: "moves_submitting", league: LEAGUE, record: { ...record("e6", 3006), day: "2026-10-25" } }, 8)).ok, true);
});

// ---------------------------------------------------------------- the open-spot claim (#199)
test("an entry with no drop: an open spot when the page shows no drop section, never a fallback drop", () => {
  const open = entry({ id: `${DAY}:${LEAGUE}:${ADD}:0`, drop: null, basis: "open", held_move: null });
  // No drop rows and no drop box: the roster has an open spot.
  const page = X.readAddPage(rawPage({ drops: false }), CLEARS);
  assert.deepEqual([page.rows, page.boxes], [[], []]);
  const check = X.pageCheck(open, page, due());
  assert.deepEqual(check, { outcome: "would_claim", reason: "open spot" });
  const line = X.moveCheck(open, check, page, due(), READ_AT);
  assert.deepEqual([line.drop, line.reason, line.controls.drops], [null, "open spot", 0]);
  assert.deepEqual(line.controls.would_fill, { action: `/nba/${LEAGUE}/${TEAM}/addplayer`, apid: ADD, dpid: null, faab: 3, submit: X.SUBMIT });
  const run = X.movesPass({ due: due(), trigger: "routine", checks: [line] });
  assert.deepEqual([run.outcome, run.reason, run.entries[0].reason], ["would_claim", null, "open spot"]);
  assert.equal(X.movesStripText({ due: due(), run, at: new Date(2026, 9, 24, 9, 2).getTime() }), "dry run · would claim for $3, into an open spot; logged 09:02");
  // A drop section shown: the roster is full. A held add names its IL move; any other says so.
  const full = X.readAddPage(rawPage(), CLEARS);
  const held = entry({ drop: null, basis: "held", held_move: { player: 2009, slot: "IL" } });
  assert.deepEqual(X.pageCheck(held, full, due()), { outcome: "skipped", reason: "the roster is full: 2009 to IL first (the page lists 11 to drop)" });
  assert.deepEqual(X.pageCheck(open, full, due()), { outcome: "skipped", reason: "the roster is full and the entry carries no drop (the page lists 11 to drop)" });
  assert.deepEqual(X.pageCheck(entry({ drop: null }), full, due()), { outcome: "skipped", reason: "the roster is full and the entry carries no drop (the page lists 11 to drop)" });
  // The skip still logs what the page showed, the drop section's size with it.
  assert.equal(X.moveCheck(held, X.pageCheck(held, full, due()), full, due(), READ_AT).controls.drops, 11);
  // A held add whose IL move was made reads as an open spot.
  assert.deepEqual(X.pageCheck(held, page, due()), { outcome: "would_claim", reason: "open spot" });
  // The other checks still hold for an entry with no drop.
  assert.equal(X.pageCheck(open, X.readAddPage(rawPage({ drops: false, heading: "Add Player" }), CLEARS), due()).reason, 'the page\'s heading is "Add Player", not the claim\'s');
  assert.equal(X.pageCheck(open, X.readAddPage(rawPage({ drops: false, waiver: "Oct 27" }), CLEARS), due()).reason, "the page's waiver date is 2026-10-27, the queue's 2026-10-26");
  assert.equal(X.pageCheck(open, X.readAddPage(rawPage({ drops: false, budget: 2 }), CLEARS), due()).reason, "the bid ($3) is outside the page's $0 to $2");
  assert.equal(X.pageCheck(open, X.readAddPage(rawPage({ drops: false, submit: null }), CLEARS), due()).reason, "the page has no claim submit");
});

test("in a live league an open spot is read, never submitted: the page is left untouched", async () => {
  const open = entry({ id: `${DAY}:${LEAGUE}:${ADD}:0`, drop: null, basis: "open", held_move: null });
  const v = await visitAdd({ answer: worker({ ...LIVE, entries: [open] }), dom: openSpotDom() });
  assert.deepEqual([ops(v), v.touched], [[...PASS, "moves_log"], []]);
  const run = sentOf(v, "moves_log")[0].run;
  assert.deepEqual([run.mode, run.outcome, run.entries[0].outcome, run.entries[0].reason, run.entries[0].controls.drops], ["live", "skipped", "skipped", X.OPEN_SPOT_HELD, 0]);
  // In a dry run the same page logs the claim it would place.
  const dry = await visitAdd({ answer: worker({ entries: [open] }), dom: openSpotDom() });
  const line = sentOf(dry, "moves_log")[0].run.entries[0];
  assert.deepEqual([line.outcome, line.reason, line.controls.would_fill.dpid, dry.touched], ["would_claim", "open spot", null, []]);
});

/** The add page with no drop section: ``addDom``'s, less my roster's rows and drop boxes. */
function openSpotDom() {
  const dom = addDom();
  const form = dom.querySelector("form#add-drop-players-form");
  const all = Object.getOwnPropertyDescriptor(form, "elements").get;
  Object.defineProperty(form, "elements", { get: () => all().filter((x) => x.name !== "dpid") });
  return { ...dom, querySelectorAll: (sel) => (sel === "table.statTable-drop tbody tr" ? [] : dom.querySelectorAll(sel)) };
}
