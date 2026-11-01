// Yahoo's Start Active Players for the rest of the week (#215, docs/AUTOPILOT.md section 2): on my
// team page opened with a start-active fragment, the league's row of the API's due (the need rule),
// the page's control as Yahoo drew it (step 0's read on #214, 2026-10-27), and the run the log
// takes. Pure but for ``pressStartActive``, the one step that clicks: the content script
// (league.js) reads the page into a plain object and calls these.
//
// What a press does (step 0): the main button runs Today Only at once (Yahoo's own PUT of the
// roster); the dialog then lists "Rest of Week N" with its own Start, whose press answers "N
// lineups updated". A repeat says the same, so the need rule and one press per run keep it from
// happening; Yahoo's words are logged as words, never read as a count. A dry run presses nothing,
// not even the main button.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.PickAndRoll = Object.assign(root.PickAndRoll || {}, api);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  /** The fragments a run starts from on my team page: the moves passes', the 05:00 daily's and
   * the side panel's. Yahoo never sees a fragment; any other visit runs nothing. */
  const START_ACTIVE_TRIGGERS = {
    "pickandroll-start-active": "routine",
    "pickandroll-start-active-late": "routine_late",
    "pickandroll-start-active-evening": "routine_evening",
    "pickandroll-start-active-daily": "routine_daily",
    "pickandroll-start-active-panel": "panel",
    // Today's page, opened from a later day's lineup set (#289).
    "pickandroll-start-active-after-lineup": "after_lineup",
  };
  const AFTER_LINEUP_FRAGMENT = "pickandroll-start-active-after-lineup";
  /** Yahoo's control (step 0): the button in its React root, the dialog it opens and the Rest of
   * Week row's Start. */
  const SA_OVERLAY = "#fantasy_start_active_overlay";
  const SA_BUTTON = "button.start-active-players";
  const SA_DIALOG = 'dialog[name="start-active-overlay"]';
  const SA_INTERVAL = "button.start-players-interval";
  /** How long the run waits for the Rest of Week row after the main press, and for Yahoo's words
   * after its Start. */
  const SA_ROWS_MS = 10 * 1000;
  const SA_ANSWER_MS = 15 * 1000;
  /** A press on record whose run was not logged within this is logged by the next visit in the
   * league with its answer not read. */
  const SA_UNREAD_MS = 60 * 1000;
  /** Yahoo's alerts on a page opened with a start-active fragment, kept by addpage.js. */
  const SA_ALERTS_ATTR = "data-pickandroll-alerts";

  /** The run's trigger from the page's fragment (``location.hash``), null when it has none. */
  function startActiveTriggerOf(hash) {
    return START_ACTIVE_TRIGGERS[String(hash || "").replace(/^#/, "")] || null;
  }

  const squash = (s) => String(s ?? "").replace(/\s+/g, " ").trim();

  /** The dialog's two rows from its text, as Yahoo printed them (``{label, range}`` each, null when
   * not shown): "Today Only Tue, Oct 27" and "Rest of Week 2 Tue, Oct 27 - Sun, Nov 01". */
  function dialogRows(text) {
    const t = squash(text);
    const day = "[A-Z][a-z]{2}, [A-Z][a-z]{2} \\d{1,2}";
    const today = new RegExp(`(Today Only) (${day})`).exec(t);
    const week = new RegExp(`(Rest of Week \\d+) (${day}(?: - ${day})?)`).exec(t);
    return {
      today: today ? { label: today[1], range: today[2] } : null,
      rest_of_week: week ? { label: week[1], range: week[2] } : null,
    };
  }

  /** Yahoo's answer in the dialog's text: ``{outcome, message}`` with its words, null before one.
   * "N lineups updated" and "We optimized …" are ``started``; "Already optimized" ``already``;
   * the error ``failed``. */
  function yahooAnswer(text) {
    const t = squash(text);
    const error = /An error occurred[^.]*\.?(?: please try again)?/i.exec(t);
    if (error) return { outcome: "failed", message: error[0] };
    const already = /Already optimized/i.exec(t);
    if (already) return { outcome: "already", message: already[0] };
    const updated = /\d+ lineups? updated|We optimized your lineups? for [^.]+\./i.exec(t);
    return updated ? { outcome: "started", message: updated[0] } : null;
  }

  /** The control as the content script read it (``{path, buttons: [{visible, disabled}],
   * outside, dialog: {present, open, text}, intervals: [{disabled}]}``) into what the run logs and
   * checks. */
  function readStartActive(raw) {
    const buttons = raw.buttons || [];
    const dialog = raw.dialog || {};
    return {
      path: raw.path || null,
      buttons: buttons.length,
      outside: raw.outside || 0,
      visible: buttons.length === 1 && Boolean(buttons[0].visible),
      disabled: buttons.length === 1 && Boolean(buttons[0].disabled),
      dialog: Boolean(dialog.present),
      open: Boolean(dialog.open),
      intervals: (raw.intervals || []).length,
    };
  }

  /** Why the run may not press on this page for ``row`` (the due route's row of the league), null
   * when it may: my team's page of the league, one visible enabled button in Yahoo's root, the
   * dialog there and closed. */
  function startActiveProblem(row, page, controls) {
    if (!page || page.kind !== "team") return "not a team page";
    if (String(page.league) !== String(row.league) || page.team !== row.team) return "not my team's page";
    if (controls.buttons !== 1) return `no single Start Active Players button in Yahoo's control (${controls.buttons} on the page)`;
    if (!controls.visible) return "the Start Active Players button is hidden";
    if (controls.disabled) return "the Start Active Players button is disabled";
    if (!controls.dialog) return "the page has no Start Active dialog";
    if (controls.open) return "the Start Active dialog was open before the run";
    return null;
  }

  /** The mode a run is in: live only where the league is live and its guard holds now; a live
   * league whose guard refuses runs dry with why. */
  function startActiveMode(row) {
    if (row.mode !== "live") return { mode: "dry_run", reason: null };
    if (row.live && row.live.ok) return { mode: "live", reason: null };
    return { mode: "dry_run", reason: `live refused: ${(row.live && row.live.reason) || "the guard did not answer"}` };
  }

  const ids = (xs) => [...new Set((xs || []).map(Number))].sort((a, b) => a - b).join(",");

  /** Whether ``a`` and ``b`` (``{players, held}`` by id) are different rosters; false when either
   * is unknown, so an unknown roster never lifts the same-day guard. */
  function rosterDiffers(a, b) {
    if (!a || !b) return false;
    return ids(a.players) !== ids(b.players) || ids(a.held) !== ids(b.held);
  }

  /** Whether ``lineup`` (the live lineup run on record in this browser, lib/lineup.js) set a swap
   * and was logged after ``record``'s press: a swap sets one day, and one press after it carries
   * it to the rest of the week (#289). */
  function lineupSince(lineup, record) {
    if (!lineup || !lineup.logged || !lineup.run || lineup.run.mode !== "live") return false;
    if (!(lineup.run.steps || []).some((x) => x.outcome === "set")) return false;
    return laterDay(lineup.run.day, record.day) && Number(lineup.at) > Number(record.at);
  }

  /** Whether ``day`` (an ISO date) is later than ``today``: the press after a lineup set is only
   * for a later day's set (the master's ruling on #289), since the main button runs Today Only at
   * once and could undo the swaps of a day set today with no pass left to fix them. */
  function laterDay(day, today) {
    return /^\d{4}-\d{2}-\d{2}$/.test(String(day)) && /^\d{4}-\d{2}-\d{2}$/.test(String(today)) && String(day) > String(today);
  }

  /** Whether the lineup run just logged (``run``, null when its log failed) wants the press after
   * it (``after_lineup``, #289): a live run with a swap set. The press is made from today's page
   * (``afterLineupUrl``), only after a later day's set, and still goes through the due's need
   * rule, STOP, the mode and the same-day guard there. */
  function pressAfterLineup(run) {
    return Boolean(run && run.mode === "live" && (run.steps || []).some((x) => x.outcome === "set"));
  }

  /** Today's team page with the after-lineup fragment, from the due row's ``page`` (today's). */
  function afterLineupUrl(page) {
    return page ? `${String(page).split("#")[0]}#${AFTER_LINEUP_FRAGMENT}` : null;
  }

  /** The set day's diff (#289): each player a set step moved whose slot on ``lineup`` (the
   * labels once settled, by id) is not the step's target, with the slot shown (null: none). */
  function setDayDiff(steps, lineup) {
    const out = {};
    for (const s of steps || []) {
      if (s.outcome !== "set") continue;
      const now = lineup[String(s.player)] ?? null;
      if (now !== s.to_slot) out[String(s.player)] = now;
    }
    return out;
  }

  /** Today's diff (#289): each player whose slot on today's labels Yahoo's press changed,
   * ``{before, after}`` (null: none shown). */
  function pressChanged(before, after) {
    const out = {};
    for (const k of new Set([...Object.keys(before || {}), ...Object.keys(after || {})])) {
      const b = (before || {})[k] ?? null;
      const a = (after || {})[k] ?? null;
      if (a !== b) out[k] = { before: b, after: a };
    }
    return out;
  }

  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  /** Whether the dialog's Today Only range ("Tue, Oct 27") is ``day`` (ISO); null when either
   * does not read. */
  function rangeIsDay(range, day) {
    const m = /([A-Z][a-z]{2}) (\d{1,2})\b/.exec(String(range || "").replace(/^[A-Z][a-z]{2}, /, ""));
    const d = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(day || ""));
    if (!m || !d) return null;
    return MONTHS[Number(d[2]) - 1] === m[1] && Number(d[3]) === Number(m[2]);
  }

  /** Why a second live run in the league today is refused (the master's rulings on #215 and
   * #214), null when it may run: ``record`` is the press on record in this browser, ``row`` the
   * due route's row read after the page was posted, ``lineup`` the live lineup run on record. One
   * per day; the guard lifts when the page's roster differs from the one the day's press ran on
   * (players or held), or when a live lineup run set a swap after it (``lineupSince``, #289). The
   * need rule's reasons never lift it alone, and an unknown roster never lifts it. */
  function sameDayProblem(record, row, day, lineup = null) {
    if (!record || record.day !== day) return null;
    if (rosterDiffers(record.roster, row.roster)) return null;
    if (lineupSince(lineup, record)) return null;
    return "Start Active ran in this league today; the roster has not changed and no lineup was set since";
  }

  function alertsOf(doc) {
    let kept;
    try {
      kept = JSON.parse((doc.documentElement && doc.documentElement.getAttribute(SA_ALERTS_ATTR)) || "[]");
    } catch (_) {
      kept = [];
    }
    return Array.isArray(kept) ? kept.map(String) : [];
  }

  /** Yahoo's two presses, once each: the main button (Today Only, at once), then, once the
   * dialog lists the Rest of Week row with its Start enabled, that Start; then Yahoo's words.
   * Every check is read again before each click. Answers ``{outcome, reason, message, today,
   * rest_of_week}``: ``skipped`` when nothing was pressed, ``failed`` after a press that did not
   * come back. Nothing else on the page is touched, no field is set and nothing is fetched. */
  async function pressStartActive(doc, { wait = (ms) => new Promise((r) => setTimeout(r, ms)), every = 200, rowsCap = SA_ROWS_MS, answerCap = SA_ANSWER_MS } = {}) {
    // The rows as the open dialog showed them, kept for a dialog that closes with Yahoo's answer.
    let shown = { today: null, rest_of_week: null };
    const rows = () => {
      const now = dialogRows(dialog() ? dialog().textContent : "");
      return { today: now.today || shown.today, rest_of_week: now.rest_of_week || shown.rest_of_week };
    };
    const out = (outcome, reason, message = null) => ({ outcome, reason, message, ...rows() });
    const buttons = [...doc.querySelectorAll(`${SA_OVERLAY} ${SA_BUTTON}`)];
    const dialog = () => doc.querySelector(SA_DIALOG);
    if (buttons.length !== 1) return out("skipped", `no single Start Active Players button (${buttons.length})`);
    if (buttons[0].disabled) return out("skipped", "the Start Active Players button is disabled");
    if (!dialog() || dialog().open) return out("skipped", "the Start Active dialog is not there, or open already");
    const before = alertsOf(doc).length;
    const yahoo = () => alertsOf(doc).slice(before);
    buttons[0].click();
    const interval = () => {
      const d = dialog();
      if (!d || !d.open || !/Rest of Week \d+/.test(squash(d.textContent))) return null;
      const found = [...d.querySelectorAll(SA_INTERVAL)];
      return found.length === 1 && !found[0].disabled ? found[0] : null;
    };
    let start = interval();
    for (let waited = 0; waited < rowsCap && !start && !yahoo().length; waited += every) {
      await wait(every);
      start = interval();
    }
    if (yahoo().length) return out("failed", `Yahoo answered the main press: "${yahoo()[0]}"`);
    const early = yahooAnswer(dialog() ? dialog().textContent : "");
    if (!start && early && early.outcome === "failed") return out("failed", "Yahoo's Today Only failed", early.message);
    if (!start) return out("failed", `the Rest of Week row did not show within ${Math.round(rowsCap / 1000)} s (Today Only ran)`);
    shown = rows();
    // Read again: the same Start, still enabled, in the dialog still open.
    if (interval() !== start) return out("failed", "the Rest of Week Start changed before its press (Today Only ran)");
    start.click();
    let answer = null;
    for (let waited = 0; waited < answerCap && !answer && !yahoo().length; waited += every) {
      await wait(every);
      answer = yahooAnswer(dialog() ? dialog().textContent : "");
    }
    if (yahoo().length) return out("failed", `Yahoo answered the Rest of Week press: "${yahoo()[0]}"`);
    if (!answer) return out("failed", `pressed; no answer read in ${Math.round(answerCap / 1000)} s`);
    return out(answer.outcome, null, answer.message);
  }

  /** The run the log takes (``POST /seasons/{league}/autopilot/start-active``), with the roster
   * it ran on: the row's, read from the page just posted. */
  function startActiveRun({ row, day, trigger, mode, outcome, reason = null, message = null, today = null, rest_of_week = null, diffs = null, controls = null, page = null, extension = null }) {
    return {
      day,
      mode,
      trigger,
      outcome,
      reason,
      reasons: row ? [...(row.reasons || [])] : [],
      today,
      rest_of_week,
      diffs,
      message,
      roster: row && row.roster ? row.roster : null,
      page,
      controls,
      extension,
    };
  }

  /** A press on record whose run was never logged, as the next visit logs it: pressed, its answer
   * not read, with the roster the press ran on; never pressed again that day unless the roster
   * changes. */
  function unreadRun(record, extension) {
    return startActiveRun({
      row: { reasons: record.reasons || [], roster: record.roster || null },
      day: record.day,
      trigger: record.trigger,
      mode: "live",
      outcome: "failed",
      reason: "pressed; Yahoo's answer was not read",
      page: record.page || null,
      extension,
    });
  }

  const SA_STRIP = {
    would_start: "would start active players for the rest of the week",
    started: "started active players",
    already: "already optimized",
    skipped: "skipped",
    failed: "failed",
    stopped: "STOP is on: nothing pressed",
  };

  /** The strip's line: the run's mode and outcome with why and Yahoo's words, or why nothing ran. */
  function startActiveStripText({ run = null, row = null, none = null, error = null, browserOff = false } = {}) {
    if (browserOff) return "off in this browser (options page)";
    if (error) return `not read: ${error}`;
    if (none) return none;
    if (!run) return row && !row.need ? "not due: nothing pressed" : "nothing ran";
    const mode = run.mode === "live" ? "live" : "dry run";
    const week = run.outcome === "started" && run.rest_of_week ? `, ${run.rest_of_week.label}` : "";
    const why = run.reason ? ` (${run.reason})` : "";
    const words = run.message ? ` · ${run.message}` : "";
    return `${mode} · ${SA_STRIP[run.outcome] || run.outcome}${week}${why}${words}`;
  }

  const SA_TRIGGER_WORDS = {
    routine: "routine",
    routine_late: "late routine",
    routine_evening: "evening routine",
    routine_daily: "daily routine",
    panel: "side panel",
    after_lineup: "after the lineup set",
    after_add: "after an add",
  };

  /** The panel's line for the last run from this browser in the league. */
  function startActiveLastText(last, when) {
    if (!last) return "no run from this browser yet";
    const mode = last.mode === "live" ? "live" : "dry run";
    const why = last.reason ? ` (${last.reason})` : "";
    const words = last.message ? ` · ${last.message}` : "";
    return `${last.day} · ${SA_TRIGGER_WORDS[last.trigger] || last.trigger}, ${mode}: ${SA_STRIP[last.outcome] || last.outcome}${why}${words}, ${when}`;
  }

  return {
    START_ACTIVE_TRIGGERS,
    SA_OVERLAY,
    SA_BUTTON,
    SA_DIALOG,
    SA_INTERVAL,
    SA_ROWS_MS,
    SA_ANSWER_MS,
    SA_UNREAD_MS,
    startActiveTriggerOf,
    dialogRows,
    yahooAnswer,
    readStartActive,
    startActiveProblem,
    startActiveMode,
    rosterDiffers,
    lineupSince,
    laterDay,
    pressAfterLineup,
    AFTER_LINEUP_FRAGMENT,
    afterLineupUrl,
    setDayDiff,
    pressChanged,
    rangeIsDay,
    sameDayProblem,
    pressStartActive,
    startActiveRun,
    unreadRun,
    startActiveStripText,
    startActiveLastText,
  };
});
