// The moves executor's page side (#171, docs/AUTOPILOT.md section 2): what Yahoo's add page
// shows, the checks a due queue entry passes on it, and the pass the log takes. Pure, so node's
// tests cover it; the content script (league.js) reads the rendered add page into a plain object
// and calls these.
//
// The routine opens each due entry's add page itself, with the fragment, in a tab of its own (the
// ruling on #171). In a dry run, or a live league whose guard refuses now, it reads the page and
// logs the claim it would place. In a live league whose guard holds (``due.live``, PR 3) and with
// every check passed, ``fillClaim`` alone touches the page, with a user's two clicks: the entry's
// one drop button (Yahoo's own script then ticks the box, posts the form's first stage and swaps
// its reply in), then, once the bid is typed and the form read back, Yahoo's final button; the
// page Yahoo lands on is read by ``readLanded``. Nothing here fetches a page, and nothing reads the
// form's anti-forgery field (it travels in the browser's own submission): the log says only
// whether it is there.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.PickAndRoll = Object.assign(root.PickAndRoll || {}, api);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  /** The fragments a pass starts from on an add page: the routine's link, its late pass and the
   * side panel's link. Yahoo never sees a fragment; any other visit runs no pass. */
  const MOVES_TRIGGERS = {
    "pickandroll-moves": "routine",
    "pickandroll-moves-late": "routine_late",
    "pickandroll-moves-panel": "panel",
  };
  const PANEL_FRAGMENT = "pickandroll-moves-panel";
  /** The add page's form, its heading and the names of its fields (the DOM read on #171). */
  const FORM_ID = "add-drop-players-form";
  const CLAIM_HEADING = "Claim Player From Waivers";
  const ADD_FIELD = "apid";
  const DROP_FIELD = "dpid";
  const BID_FIELD = "faab";
  const SUBMIT = "submit_drop_player";
  /** An entry with no drop whose page shows no drop section (#199), and why live still holds it. */
  const OPEN_SPOT = "open spot";
  const OPEN_SPOT_HELD = "open spot, read only: an open-spot claim is not submitted until Yahoo's open-spot page has been seen";
  /** Yahoo's claim step (its add page's script, read 2026-10-26, #171 0.8.2). The button beside
   * each drop box is what a user clicks: Yahoo's script, delegated on that class, then ticks the
   * box, posts the form's first stage and swaps its reply into the page, the final button with it.
   * A click on the box itself reaches none of that, and the noscript submit is never in the DOM.
   * The button names its drop in ``data-check-box-value``, with a trailing space. */
  const DROP_TRIGGER = "button.add-drop-trigger-btn";
  const DROP_TRIGGER_VALUE = "data-check-box-value";
  const SUBMIT_CONTAINER = "add-drop-submit-container";
  const SUBMIT_HIDDEN = "Hidden-submit";
  /** What the reply brings, as a hand tick showed it (2026-10-26, #171): the final button in the
   * submit container (a submit input that also carries the trigger class, so Yahoo's handler
   * takes its click), named unlike the noscript's; the stage it sets; and the drop moved from
   * the boxes, which the reply removes, to one hidden ``dpid`` field. */
  const FINAL_BUTTON = "#submit-add-drop-button.add-drop-player-submit-btn";
  const FINAL_SUBMIT = "submit_add_player";
  const FINAL_STAGE = "3";
  /** Yahoo's own bid check reads the balance off the bid field. */
  const BALANCE_ATTR = "data-faab-balance";
  /** How long the claim waits for Yahoo's reply to the tick. */
  const SWAP_MS = 15 * 1000;
  /** Yahoo's alerts on an add page opened with a moves fragment, as addpage.js records them on
   * the root element (a JSON list of their texts). */
  const ALERTS_ATTR = "data-pickandroll-alerts";
  /** How long a submit waits for its landed page in the same tab before the next pass in the
   * league logs it with its answer not read. */
  const LANDING_MS = 2 * 60 * 1000;
  /** Yahoo's anti-forgery field, by its name. The page side never reads its value and never
   * passes its name on: a pass logs only ``token``, whether the form has it (the ruling on #171). */
  const TOKEN_FIELD = "crumb";
  const TOKEN = new RegExp(TOKEN_FIELD, "i");
  /** The marker icons of a row (Yahoo's legend on the add page), by their class. */
  const MARKERS = {
    "T-action-icon-cantcut": "cantcut",
    "T-action-icon-locked": "locked",
    "T-action-icon-no-add": "no_moves",
    "T-action-icon-disabled-add": "disabled_add",
    "T-action-icon-trade": "on_team",
    "T-action-icon-notrade": "on_team",
    "T-action-icon-disabled-trade": "on_team",
  };
  /** What a page with no claim form says when the add is on a team. */
  const ON_TEAM = /owned by|is on (?:another|a|your) (?:team|roster)|already on (?:a|another) (?:team|roster)/i;
  const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];

  /** The pass's trigger from the page's fragment (``location.hash``), null when it has none. */
  function movesTriggerOf(hash) {
    return MOVES_TRIGGERS[String(hash || "").replace(/^#/, "")] || null;
  }

  /** The add page ``url`` is (``/nba/<league>/addplayer?apid=<add>``): ``{league, add}``, null
   * for any other page. */
  function addPageOf(url) {
    let u;
    try {
      u = new URL(url);
    } catch (_) {
      return null;
    }
    if (u.hostname !== "basketball.fantasysports.yahoo.com") return null;
    const m = /^\/nba\/(\d+)\/addplayer\/?$/.exec(u.pathname);
    const add = u.searchParams.get(ADD_FIELD);
    if (!m || !/^\d+$/.test(add || "")) return null;
    return { league: m[1], add: Number(add) };
  }

  /** The class names of a row's marker icons, as the markers' names. */
  function markersOf(classes) {
    const out = [];
    for (const c of String(classes || "").split(/\s+/)) if (MARKERS[c] && !out.includes(MARKERS[c])) out.push(MARKERS[c]);
    return out;
  }

  /** "Oct 26" on the page as an ISO day, in the year that puts it nearest ``near`` (an ISO day). */
  function pageDay(text, near) {
    const m = /([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})\b/.exec(String(text || ""));
    if (!m) return null;
    const month = MONTHS.indexOf(m[1].toLowerCase());
    if (month < 0) return null;
    const base = near ? new Date(`${near}T12:00:00Z`) : new Date();
    let best = null;
    for (const y of [base.getUTCFullYear() - 1, base.getUTCFullYear(), base.getUTCFullYear() + 1]) {
      const d = new Date(Date.UTC(y, month, Number(m[2]), 12));
      if (!best || Math.abs(d - base) < Math.abs(best - base)) best = d;
    }
    return best.toISOString().slice(0, 10);
  }

  /** The dollar figure after ``label`` in ``text`` ("Your Budget $100" → 100), null when absent. */
  function dollarsAfter(text, label) {
    const m = new RegExp(`${label}\\s*\\$\\s*(\\d+)`, "i").exec(String(text || ""));
    return m ? Number(m[1]) : null;
  }

  /** The add page as the content script extracted it (``{path, heading, form: {action, method,
   * fields: [{name, tag, type, value, checked}], token} | null, submit, panel, hint, add_row: {id,
   * classes} | null, rows: [{id, box, classes}], message}``, the anti-forgery field left out and
   * ``token`` saying whether the form has it) read
   * into what the checks use: the form's league and team, the add it claims, my roster's rows
   * with their markers, the bid field, its range, the budget and the waiver date shown, the
   * submit's name, and the names of the form's fields. ``near`` is the entry's clear date, for the
   * year of the page's waiver date. */
  function readAddPage(raw, near = null) {
    const form = raw.form || null;
    const all = form ? form.fields || [] : [];
    const fields = all.filter((f) => !TOKEN.test(f.name || ""));
    const named = (n) => fields.filter((f) => f.name === n);
    const add = named(ADD_FIELD)[0];
    const action = form ? form.action || null : null;
    const where = /^\/nba\/(\d+)\/(\d+)\/addplayer\/?$/.exec(action || "");
    const range = /between\s*\$\s*(\d+)\s*and\s*\$\s*(\d+)/i.exec(String(raw.hint || ""));
    const boxes = named(DROP_FIELD).filter((f) => f.type === "checkbox" && /^\d+$/.test(String(f.value)));
    const rows = (raw.rows || []).map((r) => ({
      id: Number(r.id),
      box: boxes.filter((f) => Number(f.value) === Number(r.id)).length,
      markers: markersOf(r.classes),
    }));
    const panel = String(raw.panel || "");
    return {
      path: raw.path || null,
      heading: raw.heading || null,
      action,
      league: where ? where[1] : null,
      team: where ? Number(where[2]) : null,
      method: form ? String(form.method || "").toLowerCase() || null : null,
      stage: named("stage").length > 0,
      add: add && /^\d+$/.test(String(add.value)) ? Number(add.value) : null,
      add_row: raw.add_row ? { id: Number(raw.add_row.id), markers: markersOf(raw.add_row.classes) } : null,
      rows,
      boxes: boxes.map((f) => Number(f.value)),
      cantcut: rows.filter((r) => r.markers.includes("cantcut")).map((r) => r.id),
      bid: named(BID_FIELD).length > 0,
      budget: dollarsAfter(panel, "Budget"),
      bid_min: range ? Number(range[1]) : null,
      bid_max: range ? Number(range[2]) : null,
      waiver_date: /waiver date/i.test(panel) ? pageDay(panel.split(/waiver date/i)[1], near) : null,
      submit: raw.submit || null,
      token: Boolean(form && (form.token || all.length > fields.length)),
      message: raw.message || null,
      fields: [...new Set(fields.map((f) => f.name).filter(Boolean))],
    };
  }

  /** The week of ``day`` (an ISO day) among the adds left as read (``[{start, end, adds}]``). */
  function weekOf(weeks, day) {
    return (weeks || []).find((w) => day && w.start <= day && day <= w.end) || null;
  }

  /** Why ``entry`` may not be claimed whatever its page shows, null when it may: the league's
   * state and what ``due`` says. */
  function entryProblem(entry, due) {
    if (due.mode !== "dry_run" && due.mode !== "live") return "the moves executor is off in this league";
    if (due.stop) return "STOP is on (data/autopilot/STOP)";
    if (entry.struck) return "struck: it is never executed";
    if (!entry.queued) return "not queued: it is never executed";
    const guard = entry.drop != null && (due.protected || {})[String(entry.drop)];
    if (guard) return `the drop is protected (${guard})`;
    if ((due.pending || []).some((c) => c.add === entry.add)) return "a claim on the add is pending";
    if (due.cap != null && (due.done || 0) >= due.cap) return "over the day's cap";
    const week = weekOf(due.adds_left, entry.from);
    if (week && week.adds != null && week.adds < 1) return "no adds left this week";
    return null;
  }

  /** What the add page ``page`` (``readAddPage``'s) says against ``entry``: ``{outcome, reason}``,
   * ``would_claim`` when every check passes, with no reason, or "open spot" for an entry with no
   * drop whose page shows no drop section (#199). ``due`` is the due route's answer. */
  function pageCheck(entry, page, due) {
    const skip = (reason) => ({ outcome: "skipped", reason });
    const onTeam = page.add_row && page.add_row.markers.includes("on_team");
    if (!page.action) {
      if (onTeam || (page.message && ON_TEAM.test(page.message))) return { outcome: "gone", reason: "the page shows the add on a team" };
      return skip("page not read");
    }
    if (onTeam) return { outcome: "gone", reason: "the page shows the add on a team" };
    if (page.heading !== CLAIM_HEADING) return skip(`the page's heading is "${page.heading || "none"}", not the claim's`);
    if (page.league !== String(entry.league || due.league) || page.league !== String(due.league)) return skip("the form is not this league's claim");
    if (page.team !== due.team) return skip("the form is not my team's claim");
    if (page.method !== "post") return skip("the form does not post");
    if (!page.stage || page.add == null) return skip("the form has no stage or apid field");
    if (page.add !== entry.add) return skip("the page claims another player than the entry");
    if (!page.waiver_date) return skip("the page shows no waiver date");
    if (entry.from && page.waiver_date !== entry.from) return skip(`the page's waiver date is ${page.waiver_date}, the queue's ${entry.from}`);
    if (entry.drop == null) {
      // An entry with no drop (#199): the drop section decides. Shown (any roster row or drop box),
      // the roster is full and the claim would post without the drop the page asks for; never a
      // fallback drop. None shown is an open spot.
      if (page.rows.length || page.boxes.length) {
        const held = entry.basis === "held" && entry.held_move ? entry.held_move.player : null;
        const listed = `(the page lists ${page.boxes.length} to drop)`;
        return skip(held != null ? `the roster is full: ${held} to IL first ${listed}` : `the roster is full and the entry carries no drop ${listed}`);
      }
    } else {
      const row = page.rows.filter((r) => r.id === entry.drop);
      const marker = !row.length
        ? "none"
        : row[0].markers.includes("cantcut")
          ? "cantcut"
          : row[0].markers.includes("locked")
            ? "locked"
            : row[0].box !== 1 || row.length !== 1
              ? "none"
              : null;
      if (marker) return skip(`the drop ${entry.drop} cannot be picked (${marker})`);
    }
    if (page.add_row && page.add_row.markers.includes("no_moves")) return skip("Yahoo shows no more roster moves on the add");
    if (!page.bid) return skip("the page has no bid field");
    const bid = entry.bid_placed ?? 0;
    if (!Number.isInteger(bid)) return skip(`the bid (${bid}) is not a whole dollar`);
    if (page.bid_min == null || page.bid_max == null) return skip("the page shows no bid range");
    if (bid < page.bid_min || bid > page.bid_max) return skip(`the bid ($${bid}) is outside the page's $${page.bid_min} to $${page.bid_max}`);
    if (page.budget == null || bid > page.budget) return skip(`the bid ($${bid}) is over the $${page.budget ?? "?"} left`);
    if (page.submit !== SUBMIT) return skip("the page has no claim submit");
    return { outcome: "would_claim", reason: entry.drop == null ? OPEN_SPOT : null };
  }

  /** The claim the form would carry for ``entry``: its action and the fields this pass would
   * fill, one drop only. Every other field would post as the page has it; the anti-forgery
   * field is no part of this. */
  function wouldFill(entry, page) {
    return { action: page.action, [ADD_FIELD]: entry.add, [DROP_FIELD]: entry.drop ?? null, [BID_FIELD]: entry.bid_placed ?? 0, submit: FINAL_SUBMIT };
  }

  const FILLED = new Set([ADD_FIELD, DROP_FIELD, BID_FIELD, SUBMIT, FINAL_SUBMIT]);

  /** The log's line for ``entry`` (the API's ``MoveCheck``) from its check and its page: ids,
   * dollars, dates and the page's own words for its heading only. The waiver-order table is
   * never read. ``readAt`` is when the page was read (ISO). */
  function moveCheck(entry, check, page, due, readAt) {
    const week = weekOf(due.adds_left, entry.from);
    return {
      id: entry.id,
      add: entry.add,
      drop: entry.drop ?? null,
      bid: entry.bid_placed ?? 0,
      outcome: check.outcome,
      reason: check.reason ?? null,
      page: page ? page.path : null,
      controls: page
        ? {
            action: page.action,
            method: page.method,
            heading: page.heading,
            fields: page.fields.filter((n) => !FILLED.has(n)),
            token: page.token,
            waiver_date: page.waiver_date,
            budget: page.budget,
            bid_range: page.bid_min == null ? null : [page.bid_min, page.bid_max],
            adds_left: week ? week.adds : null,
            drops: page.boxes.length,
            cantcut: page.cantcut,
            add_markers: page.add_row ? page.add_row.markers : [],
            read_at: readAt,
            would_fill: check.outcome === "would_claim" ? wouldFill(entry, page) : null,
          }
        : null,
      message: null,
    };
  }

  /** The mode a pass runs in (#171 PR 3): ``live`` only in a live league whose guard holds now
   * (``due.live``); a live league with the guard refusing runs a dry run that says why. */
  function passMode(due) {
    if (due.mode !== "live") return { mode: "dry_run", refused: null };
    if (due.live && due.live.ok) return { mode: "live", refused: null };
    return { mode: "dry_run", refused: `live refused: ${(due.live && due.live.reason) || "the guard did not answer"}` };
  }

  /** The pass the log takes (the API's ``MovesRun``): this page's one entry, as ``checks``.
   * ``due`` is the due route's answer and sets the mode (``passMode``). A live pass from the add
   * page logs only a skip: a claim that passed is submitted, and its pass is the landed page's
   * (``landedPass``). */
  function movesPass({ due, trigger, checks = [], extension = null }) {
    const { mode, refused } = passMode(due);
    const base = { day: due.date, mode, trigger, reason: null, entries: [], extension };
    if (due.stop) return { ...base, outcome: "stopped", reason: "STOP is on (data/autopilot/STOP)" };
    const would = checks.filter((c) => c.outcome === "would_claim").length;
    const failed = checks.find((c) => c.outcome === "failed");
    const first = checks.find((c) => c.reason);
    return {
      ...base,
      entries: checks,
      outcome: would ? "would_claim" : failed ? "failed" : "skipped",
      reason: refused || (would ? null : first ? first.reason : "every check failed"),
    };
  }

  /** ``due`` with the claims this browser submitted and whose pass the API does not have yet (the
   * worker's records, ``records``) counted as placed: against the day's cap, as pending claims and
   * against their week's adds, so a second page of the league never claims past them (#171 PR 3). */
  function withInflight(due, records) {
    const known = new Set((due.pending || []).map((c) => c.id));
    const mine = (records || []).filter((r) => r.line && r.day === due.date && !known.has(r.line.id));
    if (!mine.length) return due;
    const clears = (r) => (r.line.controls && r.line.controls.waiver_date) || null;
    return {
      ...due,
      done: (due.done || 0) + mine.length,
      pending: [...(due.pending || []), ...mine.map((r) => ({ id: r.line.id, add: r.line.add, drop: r.line.drop, from: clears(r) }))],
      adds_left: (due.adds_left || []).map((w) => {
        const n = mine.filter((r) => clears(r) && w.start <= clears(r) && clears(r) <= w.end).length;
        return w.adds == null || !n ? w : { ...w, adds: Math.max(0, w.adds - n) };
      }),
    };
  }

  /** Why a claim that passed every check is still not submitted live, null when it may be: a
   * free-agent add (this build places waiver claims only) or an open-spot claim, read (#199) but
   * not submitted until Yahoo's open-spot page has been seen on a real page. */
  function submitProblem(entry, page) {
    if (entry.availability === "FA" || page.heading !== CLAIM_HEADING) return "a free-agent add: this build places waiver claims only";
    if (entry.drop == null) return OPEN_SPOT_HELD;
    return null;
  }

  /** Yahoo's alerts on the page ``doc``, as addpage.js recorded them: none on a page opened
   * without a moves fragment, where Yahoo's alerts show as ever. */
  function alertsOf(doc) {
    const root = doc && doc.documentElement;
    const raw = root && typeof root.getAttribute === "function" ? root.getAttribute(ALERTS_ATTR) : null;
    try {
      const kept = JSON.parse(raw || "[]");
      return Array.isArray(kept) ? kept.map(String) : [];
    } catch (_) {
      return [];
    }
  }

  /** Why Yahoo's own check would refuse ``amount`` on the bid field ``bid`` (it alerts then and
   * submits nothing), null when it takes it: a whole number from $0 to the field's balance. A
   * field that shows no balance is refused here. */
  function bidProblem(bid, amount) {
    const balance = parseInt(bid && typeof bid.getAttribute === "function" ? bid.getAttribute(BALANCE_ATTR) : "", 10);
    if (Number.isNaN(balance)) return "the bid field shows no balance";
    if (!Number.isInteger(amount) || amount < 0 || amount > balance) return `the bid ($${amount}) is outside Yahoo's $0 to $${balance}`;
    return null;
  }

  /** The live claim on the rendered add page ``doc`` (#171 PR 3; Yahoo's claim step, 0.8.2),
   * every check passed, with a user's two clicks and nothing else: the entry's one drop button,
   * then, once Yahoo's reply is in (its final button shown and the drop picked, within ``cap``
   * ms), the bid typed and checked as Yahoo checks it and the form read back, the final button
   * once. Answers null once that is clicked, else the entry's ``{outcome, reason}``: ``failed``
   * when Yahoo alerted on the tick's reply, quoted, ``skipped`` otherwise. After an alert the final
   * button is never clicked, and the page is left as it is. The anti-forgery field travels in the
   * browser's own submission and is never read. ``wait`` is the pause between looks at the page,
   * ``every`` ms apart. */
  async function fillClaim(doc, entry, { wait = (ms) => new Promise((r) => setTimeout(r, ms)), every = 200, cap = SWAP_MS } = {}) {
    const skip = (reason) => ({ outcome: "skipped", reason });
    const form = doc.querySelector(`form#${FORM_ID}`);
    if (!form) return skip("the claim form is gone");
    const named = (n) => [...form.elements].filter((el) => el.name === n);
    const boxes = () => named(DROP_FIELD).filter((el) => String(el.type).toLowerCase() === "checkbox");
    const drop = String(entry.drop);
    if (boxes().filter((el) => String(el.value) === drop).length !== 1) return skip(`no single drop box for ${entry.drop}`);
    if (boxes().some((el) => el.checked)) return skip("a drop box was ticked before the pass");
    if (!named(BID_FIELD).length) return skip("the page has no bid field");
    const triggers = [...form.querySelectorAll(DROP_TRIGGER)].filter((b) => String(b.getAttribute(DROP_TRIGGER_VALUE) ?? "").trim() === drop);
    if (triggers.length !== 1) return skip(`no single drop button for ${entry.drop} (${triggers.length} on the page)`);
    const before = alertsOf(doc).length;
    const yahoo = () => alertsOf(doc).slice(before);
    triggers[0].click();
    // Yahoo's reply to the tick, by its three signs. The drop is picked when the form carries it
    // alone: the reply takes the boxes away and leaves one hidden field with the drop.
    const picked = () => {
      const drops = named(DROP_FIELD);
      return drops.length === 1 && String(drops[0].value) === drop && (String(drops[0].type).toLowerCase() === "hidden" || drops[0].checked);
    };
    const signs = () => {
      const box = doc.getElementById(SUBMIT_CONTAINER);
      return {
        final: box ? box.querySelector(FINAL_BUTTON) : null,
        shown: Boolean(box) && !String(box.className || "").split(/\s+/).includes(SUBMIT_HIDDEN),
        picked: picked(),
      };
    };
    let s = signs();
    for (let waited = 0; waited < cap && !(s.final && s.shown && s.picked) && !yahoo().length; waited += every) {
      await wait(every);
      s = signs();
    }
    if (yahoo().length) return { outcome: "failed", reason: `Yahoo answered the drop's tick: "${yahoo()[0]}"` };
    const missing = [!s.final && "the final button is not there", !s.shown && "the submit is still hidden", !s.picked && "the form does not carry the drop alone"].filter(Boolean);
    if (missing.length) return skip(`Yahoo's claim step did not come back within ${Math.round(cap / 1000)} s: ${missing.join("; ")}`);
    const [bid] = named(BID_FIELD);
    if (!bid) return skip("the page has no bid field once the drop was ticked");
    const amount = entry.bid_placed ?? 0;
    const refused = bidProblem(bid, amount);
    if (refused) return skip(refused);
    bid.value = String(amount);
    bid.dispatchEvent(new Event("input", { bubbles: true }));
    bid.dispatchEvent(new Event("change", { bubbles: true }));
    const drops = named(DROP_FIELD).map((el) => String(el.value));
    const add = named(ADD_FIELD);
    const stage = named("stage");
    const wrong = [];
    if (!picked()) wrong.push(`its drops are ${drops.join(", ") || "none"}`);
    if (stage.length !== 1 || String(stage[0].value) !== FINAL_STAGE) wrong.push(`its stage reads ${stage.map((el) => el.value).join(", ") || "none"}`);
    if (add.length !== 1 || Number(add[0].value) !== entry.add) wrong.push("its apid is not the add");
    if (bid.value !== String(amount)) wrong.push(`its bid reads ${bid.value}`);
    // The final button by its identity: still the one Yahoo drew, shown, and named as the claim's.
    const now = signs();
    if (now.final !== s.final || !now.shown || s.final.getAttribute("name") !== FINAL_SUBMIT) wrong.push("its final button is not the claim's");
    if (wrong.length) return skip(`the form did not take the claim: ${wrong.join("; ")}`);
    if (yahoo().length) return skip(`Yahoo alerted before the final click: "${yahoo()[0]}"`);
    s.final.click();
    // Yahoo's handler checks the bid as it runs: an alert then means nothing was sent.
    if (yahoo().length) return skip(`Yahoo refused the final click: "${yahoo()[0]}"`);
    return null;
  }

  /** Yahoo's words saying a claim went in. */
  const PLACED = /\b(?:claim|transaction|request)\b[^.]{0,60}\b(?:submitted|placed|received|successful)|successfully (?:submitted|placed|added|processed|created)|pending (?:claim|waiver|transaction)/i;
  /** An error worth the name has words: Yahoo's red stat figures ("(-5)") share its classes. */
  const WORDS = /[A-Za-z]{3}/;

  /** What the page Yahoo lands on after a claim's submit says (#171 PR 3), from the content
   * script's plain read ``{path, heading, form, notes, errors, pending, claim}``: ``claimed`` when
   * the page links the claim among its pending transactions (``claim``: a View Waiver link whose
   * claim id is this add and drop), says the claim went in or shows the add among pending claims;
   * ``failed`` with Yahoo's words when an error stands on the page or the claim form came back
   * with a message; null when the answer is not recognised (logged ``claimed``, its answer not
   * read: the ruling on #171). The real page (2026-10-26) lands on my team page with "You have
   * successfully created a waiver claim for … dropping …", the claim's link, and red stat
   * figures in the error classes. */
  function readLanded(raw) {
    const notes = (raw.notes || []).filter(Boolean);
    const errors = (raw.errors || []).filter((x) => WORDS.test(x || ""));
    const placed = [...notes, ...errors, raw.heading || ""].filter(Boolean).find((x) => PLACED.test(x));
    if (placed) return { outcome: "claimed", message: placed };
    if (raw.claim) return { outcome: "claimed", message: "the claim shows among the pending transactions" };
    if (errors.length) return { outcome: "failed", message: errors[0] };
    if (raw.form && notes.length) return { outcome: "failed", message: notes[0] };
    if (raw.pending && !raw.form) return { outcome: "claimed", message: "the add shows among the pending claims" };
    return null;
  }

  /** The reason a claim whose answer was not read carries: it may be placed, so it counts. */
  function unreadReason(at) {
    return `submitted ${clockOf(at)}; Yahoo's answer was not read: check the pending claims`;
  }

  /** The live pass for a submitted claim (``record``, kept by the worker from the add page's
   * read) once its answer is known: ``landed`` is ``readLanded``'s answer, null when it was not
   * recognised or never read; ``seen`` the landed page's path and heading. */
  function landedPass(record, landed, seen = null, extension = null) {
    const outcome = landed ? landed.outcome : "claimed";
    const reason = !landed ? unreadReason(record.at) : outcome === "failed" ? landed.message : null;
    const line = {
      ...record.line,
      outcome,
      reason,
      message: landed ? landed.message : null,
      controls: { ...record.line.controls, landed: seen },
    };
    return { day: record.day, mode: "live", trigger: record.trigger, outcome, reason: outcome === "failed" ? reason : null, entries: [line], extension };
  }

  /** "05:02", a time on this machine's clock. */
  function clockOf(at) {
    const d = new Date(at);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }

  const MOVES_MODE_WORDS = { dry_run: "dry run", live: "live", off: "off" };

  /** The strip's line on an add page: the brake, the league's mode and STOP, then the pass's
   * outcome at ``at``, or why this page had none. */
  function movesStripText({ browserOff = false, due = null, run = null, at = Date.now(), error = null, none = false }) {
    if (browserOff) return "off in this browser (the extension's settings)";
    if (error) return `not reached: ${error}`;
    if (!due) return "reading the queue…";
    if (due.mode === "off") return "off in this league";
    if (due.stop) return "STOP is on: nothing runs";
    const mode = MOVES_MODE_WORDS[due.mode] || due.mode;
    if (none) return `${mode} · this player is not due in the queue: nothing logged`;
    if (!run) return `${mode} · ${due.reason || "nothing due now"}`;
    const e = run.entries[0];
    const refused = run.mode === "dry_run" && due.mode === "live" ? ` (${passMode(due).refused})` : "";
    const head = run.mode === "live" ? "live" : `dry run${refused}`;
    if (run.outcome === "would_claim") return `${head} · would claim for $${e.bid}, ${dropWords(e.drop)}; logged ${clockOf(at)}`;
    const what = e && e.outcome === "gone" ? "gone" : run.outcome === "failed" ? "failed" : "skipped";
    return `${head} · ${what}: ${(e && e.reason) || run.reason} (${clockOf(at)})`;
  }

  /** "dropping 2005", or "into an open spot" for a claim with no drop. */
  function dropWords(drop) {
    return drop == null ? "into an open spot" : `dropping ${drop}`;
  }

  /** The strip's line on the page Yahoo landed on after a claim's submit: what was logged. */
  function landedStripText(run, at = Date.now()) {
    const e = run.entries[0];
    if (e.outcome === "failed") return `live · claim failed: ${e.reason} (${clockOf(at)})`;
    const said = e.reason || (e.message ? `Yahoo: ${e.message}` : "placed");
    return `live · claimed for $${e.bid}, ${dropWords(e.drop)}: ${said}; logged ${clockOf(at)}`;
  }

  const MOVES_OUTCOME_WORDS = {
    would_claim: "would claim",
    nothing_due: "nothing due",
    skipped: "skipped",
    claimed: "claimed",
    failed: "failed",
    stopped: "stopped by STOP",
  };
  const MOVES_TRIGGER_WORDS = { routine: "routine", routine_late: "late routine", panel: "side panel" };

  /** The panel's line for the league's last pass from this browser (the worker keeps it):
   * "2026-10-24 · routine: would claim, 3 min ago". ``when`` is its age in words. */
  function movesLastText(last, when) {
    if (!last) return "no pass from this browser yet";
    const why = last.reason ? ` (${last.reason})` : "";
    return `${last.day} · ${MOVES_TRIGGER_WORDS[last.trigger] || last.trigger}: ${MOVES_OUTCOME_WORDS[last.outcome] || last.outcome}${why}, ${when}`;
  }

  /** The panel's links to the league's due entries' add pages, with the panel's fragment: the
   * user opens each; nothing is opened for them. In a live league whose guard holds, opening one
   * places the claim, and the link says so; an open spot is only read there (#199). */
  function dueLinks(due, site = "https://basketball.fantasysports.yahoo.com") {
    const live = passMode(due).mode === "live";
    return (due.entries || []).map((e) => ({
      id: e.id,
      href: `${site}${e.page}#${PANEL_FRAGMENT}`,
      text: `${live && e.drop != null ? "claim: " : ""}add ${e.add}, ${e.drop == null ? "open spot" : `drop ${e.drop}`}, $${e.bid_placed ?? 0}`,
    }));
  }

  /** The league of a Yahoo league page (``/nba/<league>/…``), null elsewhere: any of them may be
   * the page a claim's submit lands on. */
  function leagueOfPage(url) {
    let u;
    try {
      u = new URL(url);
    } catch (_) {
      return null;
    }
    if (u.hostname !== "basketball.fantasysports.yahoo.com") return null;
    const m = /^\/nba\/(\d+)(?:\/|$)/.exec(u.pathname);
    return m ? m[1] : null;
  }

  return {
    MOVES_TRIGGERS,
    FORM_ID,
    CLAIM_HEADING,
    SUBMIT,
    OPEN_SPOT,
    OPEN_SPOT_HELD,
    DROP_TRIGGER,
    DROP_TRIGGER_VALUE,
    SUBMIT_CONTAINER,
    SUBMIT_HIDDEN,
    FINAL_BUTTON,
    FINAL_SUBMIT,
    FINAL_STAGE,
    BALANCE_ATTR,
    SWAP_MS,
    ALERTS_ATTR,
    LANDING_MS,
    TOKEN_FIELD,
    TOKEN,
    MARKERS,
    movesTriggerOf,
    addPageOf,
    markersOf,
    pageDay,
    readAddPage,
    entryProblem,
    pageCheck,
    wouldFill,
    moveCheck,
    passMode,
    movesPass,
    withInflight,
    submitProblem,
    alertsOf,
    bidProblem,
    fillClaim,
    readLanded,
    unreadReason,
    landedPass,
    leagueOfPage,
    movesStripText,
    landedStripText,
    movesLastText,
    dueLinks,
  };
});
