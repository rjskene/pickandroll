// The moves executor's page side (#171, docs/AUTOPILOT.md section 2): what Yahoo's add page
// shows, the checks a due queue entry passes on it, and the pass the log takes. Pure, so node's
// tests cover it; the content script (league.js) reads the rendered add page into a plain object
// and calls these.
//
// The routine opens each due entry's add page itself, with the fragment, in a tab of its own (the
// ruling on #171): this build is the dry run there. It reads the page and logs the claim it would
// place. Nothing here toggles a drop, types a bid or submits the form, nothing fetches a page,
// and nothing reads the form's anti-forgery field: the log says only whether it is there.
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
    if (entry.drop == null) return "an open-spot claim is not read yet";
    const guard = (due.protected || {})[String(entry.drop)];
    if (guard) return `the drop is protected (${guard})`;
    if ((due.pending || []).some((c) => c.add === entry.add)) return "a claim on the add is pending";
    if (due.cap != null && (due.done || 0) >= due.cap) return "over the day's cap";
    const week = weekOf(due.adds_left, entry.from);
    if (week && week.adds != null && week.adds < 1) return "no adds left this week";
    return null;
  }

  /** What the add page ``page`` (``readAddPage``'s) says against ``entry``: ``{outcome, reason}``,
   * ``would_claim`` with no reason when every check passes. ``due`` is the due route's answer. */
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
    if (page.add_row && page.add_row.markers.includes("no_moves")) return skip("Yahoo shows no more roster moves on the add");
    if (!page.bid) return skip("the page has no bid field");
    const bid = entry.bid_placed ?? 0;
    if (!Number.isInteger(bid)) return skip(`the bid (${bid}) is not a whole dollar`);
    if (page.bid_min == null || page.bid_max == null) return skip("the page shows no bid range");
    if (bid < page.bid_min || bid > page.bid_max) return skip(`the bid ($${bid}) is outside the page's $${page.bid_min} to $${page.bid_max}`);
    if (page.budget == null || bid > page.budget) return skip(`the bid ($${bid}) is over the $${page.budget ?? "?"} left`);
    if (page.submit !== SUBMIT) return skip("the page has no claim submit");
    return { outcome: "would_claim", reason: null };
  }

  /** The claim the form would carry for ``entry``: its action and the fields this pass would
   * fill, one drop only. Every other field would post as the page has it; the anti-forgery
   * field is no part of this. */
  function wouldFill(entry, page) {
    return { action: page.action, [ADD_FIELD]: entry.add, [DROP_FIELD]: entry.drop, [BID_FIELD]: entry.bid_placed ?? 0, submit: SUBMIT };
  }

  const FILLED = new Set([ADD_FIELD, DROP_FIELD, BID_FIELD, SUBMIT]);

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

  /** The pass the log takes (the API's ``MovesRun``): this page's one entry, as ``checks``.
   * ``due`` is the due route's answer. This build always logs a dry run: it claims nothing,
   * whatever the league's mode. */
  function movesPass({ due, trigger, checks = [], extension = null }) {
    const base = { day: due.date, mode: "dry_run", trigger, reason: null, entries: [], extension };
    if (due.stop) return { ...base, outcome: "stopped", reason: "STOP is on (data/autopilot/STOP)" };
    const would = checks.filter((c) => c.outcome === "would_claim").length;
    const failed = checks.find((c) => c.outcome === "failed");
    const first = checks.find((c) => c.reason);
    return {
      ...base,
      entries: checks,
      outcome: would ? "would_claim" : failed ? "failed" : "skipped",
      reason: would ? null : first ? first.reason : "every check failed",
    };
  }

  /** "05:02", a time on this machine's clock. */
  function clockOf(at) {
    const d = new Date(at);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }

  const MOVES_MODE_WORDS = { dry_run: "dry run", live: "live (this build logs only)", off: "off" };

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
    if (run.outcome === "would_claim") {
      const e = run.entries[0];
      return `${mode} · would claim for $${e.bid}, dropping ${e.drop}; logged ${clockOf(at)}`;
    }
    const e = run.entries[0];
    const what = e && e.outcome === "gone" ? "gone" : run.outcome === "failed" ? "failed" : "skipped";
    return `${mode} · ${what}: ${run.reason} (${clockOf(at)})`;
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
   * user opens each; nothing is opened for them. */
  function dueLinks(due, site = "https://basketball.fantasysports.yahoo.com") {
    return (due.entries || []).map((e) => ({
      id: e.id,
      href: `${site}${e.page}#${PANEL_FRAGMENT}`,
      text: `add ${e.add}, drop ${e.drop ?? "none"}, $${e.bid_placed ?? 0}`,
    }));
  }

  return {
    MOVES_TRIGGERS,
    FORM_ID,
    CLAIM_HEADING,
    SUBMIT,
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
    movesPass,
    movesStripText,
    movesLastText,
    dueLinks,
  };
});
