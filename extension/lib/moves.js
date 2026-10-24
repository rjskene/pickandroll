// The moves executor's page side (#171, docs/AUTOPILOT.md section 2): what Yahoo's add page
// shows, the checks every due queue entry passes on it, and the pass the log takes. Pure, so
// node's tests cover it; the content script (league.js) reads each add page into a plain object
// and calls these.
//
// This build is the dry run: it reads the add page and logs the claim it would place. Nothing here
// toggles a drop, sets the bid or submits the form, and nothing reads the form's crumb.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.PickAndRoll = Object.assign(root.PickAndRoll || {}, api);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  /** The fragments a pass starts from on my team page: the routine's link and its late pass.
   * Yahoo never sees a fragment. Any other visit runs no pass. */
  const MOVES_TRIGGERS = { "pickandroll-moves": "routine", "pickandroll-moves-late": "routine_late" };
  /** The add page's form and the names of its fields (the DOM read on #171). */
  const FORM_ID = "add-drop-players-form";
  const ADD_FIELD = "apid";
  const DROP_FIELD = "dpid";
  const BID_FIELD = "faab";
  const SUBMIT = "submit_drop_player";
  /** What the page says when the add is no longer there to claim. */
  const GONE = /no longer available|not available|already (?:on|been added|owned)|is on (?:a|another) (?:team|roster)/i;
  const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];

  /** The pass's trigger from the page's fragment (``location.hash``), null when it has none. */
  function movesTriggerOf(hash) {
    return MOVES_TRIGGERS[String(hash || "").replace(/^#/, "")] || null;
  }

  /** The add page of ``add`` in ``league``: Yahoo's own add link, a GET that adds nothing. */
  function addPath(league, add) {
    return `/nba/${league}/addplayer?apid=${add}`;
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
   * fields: [{name, tag, type, value, checked}]} | null, token, submit, panel, hint, cantcut,
   * no_moves, message}``, the crumb taken out before the read) read into what the checks use:
   * the form's action, the add it claims, the drops it offers, the bid field, the budget and
   * waiver date it shows, Yahoo's markers, and the names of its fields. ``near`` is the entry's
   * clear date, for the year of the page's waiver date. */
  function readAddPage(raw, near = null) {
    const form = raw.form || null;
    const fields = form ? form.fields || [] : [];
    const named = (n) => fields.filter((f) => f.name === n);
    const add = named(ADD_FIELD)[0];
    const budget = dollarsAfter(raw.panel, "Budget");
    const range = /between\s*\$\s*(\d+)\s*and\s*\$\s*(\d+)/i.exec(String(raw.hint || ""));
    return {
      path: raw.path || null,
      heading: raw.heading || null,
      action: form ? form.action || null : null,
      method: form ? String(form.method || "").toLowerCase() || null : null,
      add: add && /^\d+$/.test(String(add.value)) ? Number(add.value) : null,
      stage: (named("stage")[0] || {}).value ?? null,
      drops: named(DROP_FIELD)
        .filter((f) => f.type === "checkbox" && /^\d+$/.test(String(f.value)))
        .map((f) => Number(f.value)),
      bid: named(BID_FIELD).length > 0,
      budget,
      bid_max: range ? Number(range[2]) : budget,
      waiver_date: /waiver date/i.test(String(raw.panel || "")) ? pageDay(String(raw.panel).split(/waiver date/i)[1], near) : null,
      submit: raw.submit || null,
      token: Boolean(raw.token),
      cantcut: Number(raw.cantcut) || 0,
      no_moves: Boolean(raw.no_moves),
      message: raw.message || null,
      fields: [...new Set(fields.map((f) => f.name).filter(Boolean))],
    };
  }

  /** The week of ``day`` (an ISO day) among the adds left as read (``[{start, end, adds}]``). */
  function weekOf(weeks, day) {
    return (weeks || []).find((w) => day && w.start <= day && day <= w.end) || null;
  }

  /** Why ``entry`` is not taken to its add page, null when it is: what ``due`` and the pass so far
   * say, before any page is read. ``pass`` holds the claims this pass would place before it. */
  function entryProblem(entry, due, pass) {
    if (entry.struck) return "struck: it is never executed";
    if (!entry.queued) return "not queued: it is never executed";
    if (entry.drop == null) return "an open-spot claim is not read yet";
    const guard = (due.protected || {})[String(entry.drop)];
    if (guard) return `the drop is protected (${guard})`;
    if ((due.pending || []).some((c) => c.add === entry.add)) return "a claim on the add is pending";
    if (pass.some((c) => c.add === entry.add)) return "this pass claims the add already";
    if (pass.some((c) => c.drop === entry.drop)) return "this pass drops that player already";
    if (due.cap != null && (due.done || 0) + pass.length >= due.cap) return "over the day's cap";
    const week = weekOf(due.adds_left, entry.from);
    if (week && week.adds != null) {
      const placed = pass.filter((c) => weekOf(due.adds_left, c.from) === week).length;
      if (week.adds - placed < 1) return "no adds left this week";
    }
    return null;
  }

  /** What the add page ``page`` (``readAddPage``'s) says against ``entry``: ``{outcome, reason}``,
   * ``would_claim`` with no reason when every check passes. ``due`` is the due route's answer for
   * my team in this league. */
  function pageCheck(entry, page, due) {
    const skip = (reason) => ({ outcome: "skipped", reason });
    const [where, query = ""] = String(page.path || "").split("?");
    if (where !== `/nba/${due.league}/addplayer` || new URLSearchParams(query).get(ADD_FIELD) !== String(entry.add)) {
      return skip(`the add page answered ${page.path || "nothing"}`);
    }
    if (!page.action) {
      if (page.message && GONE.test(page.message)) return { outcome: "gone", reason: page.message };
      return skip("the add page has no claim form");
    }
    if (page.action !== `/nba/${due.league}/${due.team}/addplayer`) return skip("the form is not my team's claim");
    if (page.method !== "post") return skip("the form does not post");
    if (page.add !== entry.add) return skip("the page claims another player than the entry");
    if (entry.availability === "W" || entry.availability == null) {
      if (!page.waiver_date) return skip("the page shows no waiver date: the add is not on waivers");
      if (entry.from && page.waiver_date !== entry.from) {
        return skip(`the page's waiver date is ${page.waiver_date}, the queue's ${entry.from}`);
      }
    } else {
      return skip("a free-agent add is not read yet");
    }
    if (!page.drops.includes(entry.drop)) {
      return skip("the drop has no control on the page (not on my roster, or on Yahoo's can't-cut list)");
    }
    if (page.no_moves) return skip("Yahoo shows no moves left");
    if (!page.bid) return skip("the page has no bid field");
    const bid = entry.bid_placed ?? 0;
    const left = page.budget ?? due.budget;
    if (left == null) return skip("the page shows no budget");
    if (bid > left || (page.bid_max != null && bid > page.bid_max)) return skip(`the bid ($${bid}) is over the $${left} left`);
    if (page.submit !== SUBMIT) return skip("the page has no claim submit");
    return { outcome: "would_claim", reason: null };
  }

  /** The claim the form would carry for ``entry``: the fields this pass would fill, by name. Every
   * other field would post as the page has it; the crumb is no part of this. */
  function wouldFill(entry) {
    return { [ADD_FIELD]: entry.add, [DROP_FIELD]: entry.drop, [BID_FIELD]: entry.bid_placed ?? 0, submit: SUBMIT };
  }

  /** The log's line for ``entry`` (the API's ``MoveCheck``), from its check and its page, if read. */
  function moveCheck(entry, check, page = null) {
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
            fields: page.fields,
            drops: page.drops.length,
            cantcut: page.cantcut,
            budget: page.budget,
            waiver_date: page.waiver_date,
            no_moves: page.no_moves,
            token: page.token,
            submit: page.submit,
            would_fill: check.outcome === "would_claim" ? wouldFill(entry) : null,
          }
        : null,
      message: null,
    };
  }

  /** The pass the log takes (the API's ``MovesRun``). ``due`` is the due route's answer, ``checks``
   * every due entry's ``moveCheck``, ``error`` why the pass could not run. This build always logs a
   * dry run: it claims nothing, whatever the league's mode. */
  function movesPass({ due, trigger, checks = [], error = null, extension = null }) {
    const base = { day: due.date, mode: "dry_run", trigger, reason: null, entries: [], extension };
    if (due.stop) return { ...base, outcome: "stopped", reason: "STOP is on (data/autopilot/STOP)" };
    if (error) return { ...base, outcome: "failed", reason: error, entries: checks };
    if (!(due.entries || []).length) return { ...base, outcome: "nothing_due", reason: due.reason || "nothing due now" };
    const would = checks.filter((c) => c.outcome === "would_claim").length;
    return {
      ...base,
      entries: checks,
      outcome: would ? "would_claim" : "skipped",
      reason: would ? null : "every due entry failed a check",
    };
  }

  /** "05:02", a time on this machine's clock. */
  function clockOf(at) {
    const d = new Date(at);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }

  const MOVES_MODE_WORDS = { dry_run: "dry run", live: "live (this build logs only)", off: "off" };

  /** The strip's moves line after a pass (or a pass not run): the brake, the league's mode and
   * STOP, then the pass's outcome at ``at``. */
  function movesStripText({ browserOff = false, due = null, run = null, at = Date.now(), error = null }) {
    if (browserOff) return "off in this browser (the extension's settings)";
    if (error) return `not reached: ${error}`;
    if (!due) return "reading the queue…";
    if (due.mode === "off") return "off in this league";
    if (due.stop) return "STOP is on: nothing runs";
    const mode = MOVES_MODE_WORDS[due.mode] || due.mode;
    if (!run) return `${mode} · ${due.reason || "nothing due now"}`;
    const n = run.entries.filter((e) => e.outcome === "would_claim").length;
    if (run.outcome === "would_claim") return `${mode} · ${n} claim${n === 1 ? "" : "s"} logged ${clockOf(at)}`;
    if (run.outcome === "nothing_due") return `${mode} · ${run.reason}, logged ${clockOf(at)}`;
    return `${mode} · ${run.outcome === "failed" ? "failed" : "skipped"}: ${run.reason} (${clockOf(at)})`;
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
   * "2026-10-24 · routine: would claim 2, 3 min ago". ``when`` is its age in words. */
  function movesLastText(last, when) {
    if (!last) return "no pass from this browser yet";
    const n = last.claims || 0;
    const claims = last.outcome === "would_claim" ? ` ${n}` : "";
    const why = last.reason ? ` (${last.reason})` : "";
    return `${last.day} · ${MOVES_TRIGGER_WORDS[last.trigger] || last.trigger}: ${MOVES_OUTCOME_WORDS[last.outcome] || last.outcome}${claims}${why}, ${when}`;
  }

  return {
    MOVES_TRIGGERS,
    FORM_ID,
    SUBMIT,
    movesTriggerOf,
    addPath,
    pageDay,
    readAddPage,
    entryProblem,
    pageCheck,
    wouldFill,
    moveCheck,
    movesPass,
    movesStripText,
    movesLastText,
  };
});
